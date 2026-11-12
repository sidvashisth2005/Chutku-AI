"""The local model gets a short, relevant tool menu (2.3x faster planning) and can fall back to every tool."""
from pathlib import Path
import tempfile
import unittest

import chutku.agent_loop as al
from chutku.app import create_runtime


class ToolMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        with create_runtime(Path(cls.temp.name)) as runtime:
            cls.rows = al.planner_tool_rows(runtime)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def menu(self, goal, steps=()):
        session = al.AgentSession(goal, mode="auto_safe")
        session.steps = [{"tool": tool, "state": "COMPLETED", "arguments": {}, "observation": "{}"} for tool in steps]
        return {row["name"] for row in al.relevant_rows(self.rows, session)}

    def test_core_tools_exist(self):
        self.assertEqual(al.CORE_TOOLS - {row["name"] for row in self.rows}, set())

    def test_menu_is_short_and_has_the_needed_tool(self):
        cases = {"set the volume to 30 and lower the brightness": {"audio.volume", "display.brightness"},
                 "schedule a shutdown in 1 hour": {"power.schedule"},
                 r"zip the folder D:\x": {"files.zip"},
                 "mere liye snake game banao": {"code.build_project"},
                 "switch audio to headphones": {"audio.set_output"},
                 "what is on my clipboard": {"clipboard.read_text"},
                 "remind me tomorrow to pay rent": {"reminder.set"}}
        for goal, needed in cases.items():
            menu = self.menu(goal)
            self.assertLessEqual(len(menu), len(al.CORE_TOOLS) + al.MENU_EXTRA, goal)
            self.assertLess(len(menu), len(self.rows), goal)
            self.assertTrue(needed <= menu, (goal, needed - menu))

    def test_tools_already_used_stay_on_the_menu(self):
        self.assertIn("uia.invoke", self.menu("continue", steps=["uia.invoke"]))

    def test_cannot_do_with_short_menu_retries_with_every_tool(self):
        class Service:
            def __init__(self):
                self.menus = []

            def complete(self, messages, *, schema, schema_name, max_tokens, check=None):
                forms = schema["properties"]["next_steps"]["items"]["anyOf"]
                self.menus.append(len(forms))
                if len(self.menus) == 1:
                    return {"status": "clarify", "reply": "No tool for that.", "declared_plan": [], "next_steps": [],
                            "finish": False}, {}
                return {"status": "done", "reply": "ok", "declared_plan": [], "next_steps": [], "finish": True}, {}

        service = Service()
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            session = al.AgentSession("do the obscure thing", mode="auto_safe")
            proposal, meta = al.LocalAgentPlanner(service).propose(session, runtime)
        self.assertEqual(proposal["status"], "done")
        self.assertLess(service.menus[0], service.menus[1])          # short menu first, then every tool
        self.assertEqual(service.menus[1], meta["tools_offered"])


class ThinkingTests(unittest.TestCase):
    def test_only_numeric_questions_with_nothing_to_do_are_reasoning_questions(self):
        for goal in ("2 ki power 10 aur 10 ka cube, kaun bada hai", "17 times 23 kitna hota hai?",
                     "Ek shirt 800 ki hai, 25 percent discount. Kitne ki padegi?", "what is 15% of 640?"):
            self.assertTrue(al._reasoning_question(goal), goal)
        for goal in ("D drive mein kitni jagah khali hai", "open notepad", "remind me in 10 minutes",
                     "10 baje ka alarm set karo", r"D:\Notes\2026 mein kitni files hain?", "What's the weather?"):
            self.assertFalse(al._reasoning_question(goal), goal)

    def test_the_planner_thinks_on_the_first_round_of_a_reasoning_question_only(self):
        class Service:
            thinks = []

            def complete(self, messages, *, schema, schema_name, max_tokens, check=None, think=False):
                Service.thinks.append(think)
                return {"status": "done", "reply": "1024 bada hai.", "declared_plan": [], "next_steps": [],
                        "finish": True}, {}
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            planner = al.LocalAgentPlanner(Service())
            planner.propose(al.AgentSession("2 ki power 10 aur 10 ka cube, kaun bada hai", mode="owner"), runtime)
            planner.propose(al.AgentSession("open notepad", mode="owner"), runtime)
            asked = al.AgentSession("dhyan se socho: open notepad", mode="owner")
            asked.think = True                                       # H21, set by the dashboard
            planner.propose(asked, runtime)
            later = al.AgentSession("2 ki power 10 aur 10 ka cube, kaun bada hai", mode="owner")
            later.steps.append({"tool": "system.get_time", "state": "COMPLETED", "arguments": {}, "purpose": "p",
                                "observation": {"time": "18:40"}})
            planner.propose(later, runtime)                          # a later round: no thinking
        self.assertEqual(Service.thinks, [True, False, True, False])


class PartsTests(unittest.TestCase):
    GOAL = (r"D:\ChutkuScratch\onecmd mein report naam ka folder banao, usme todo.txt mein 'buy milk' likho, "
            "phir us folder ki files batao")

    def test_a_several_part_request_splits_into_its_parts_and_one_thing_stays_one(self):
        self.assertEqual(al.goal_parts(self.GOAL), [r"D:\ChutkuScratch\onecmd mein report naam ka folder banao",
                                                    "usme todo.txt mein 'buy milk' likho", "us folder ki files batao"])
        for goal in ("RAM aur CPU kitna use ho raha hai", "what is the weather and time in Pune", "open notepad"):
            self.assertEqual(al.goal_parts(goal), [], goal)

    def test_the_local_model_gets_one_part_at_a_time_and_cannot_finish_early(self):
        import json
        from chutku.profiles import QWEN
        session = al.AgentSession(self.GOAL, mode="owner")
        seen = json.loads(session.planner_input(profile=QWEN))
        self.assertEqual(seen["DO_NOW"], r"D:\ChutkuScratch\onecmd mein report naam ka folder banao")
        self.assertEqual(len(seen["PARTS"]), 3)
        self.assertNotIn("DO_NOW", json.loads(session.planner_input()))   # cloud planners read the whole goal
        with self.assertRaisesRegex(ValueError, "still to do: usme todo.txt"):
            session._reject_early_finish({"status": "done", "reply": "Folder made.", "next_steps": [],
                                          "finish": True})
        act = {"status": "continue", "reply": "", "finish": True, "next_steps": [
            {"tool": "filesystem.create_directory", "arguments": {"path": r"D:\ChutkuScratch\onecmd\report"},
             "purpose": "make the folder"}]}
        session._reject_early_finish(act)
        self.assertFalse(act["finish"])                   # later parts remain: never finish after part 1
        session.part, act["finish"] = 2, True             # the last part: finishing is allowed again
        session._reject_early_finish(act)
        self.assertTrue(act["finish"])


class SafetyRefusalTests(unittest.TestCase):
    def test_safety_refusals_are_not_retried_with_every_tool(self):
        class Service:
            calls = 0

            def complete(self, messages, *, schema, schema_name, max_tokens, check=None):
                Service.calls += 1
                return {"status": "clarify", "reply": "System32 is a protected system folder; I cannot delete it.",
                        "declared_plan": [], "next_steps": [], "finish": False}, {}
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            session = al.AgentSession(r"Delete everything in C:\Windows\System32", mode="auto_safe")
            proposal, _meta = al.LocalAgentPlanner(Service()).propose(session, runtime)
        self.assertEqual((proposal["status"], Service.calls), ("clarify", 1))


if __name__ == "__main__":
    unittest.main()

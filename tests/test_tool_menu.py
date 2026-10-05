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

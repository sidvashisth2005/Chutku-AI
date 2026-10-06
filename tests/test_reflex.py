"""Reflex Compiler (master plan S17): learned instant skills from verified model plans."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku import reflex
from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.core.ledger import target_key
from chutku.quick_intents import QuickPlanner, quick_proposal

APPS = [{"name": "Spotify", "app_id": "Spotify.App"}, {"name": "Calculator", "app_id": "Calc"}]


def row(goal, *steps, planners=("local",), **extra):
    return {"goal": goal, "steps": [{"tool": t, "purpose": p, "arguments": a} for t, a, p in steps], "at": time.time(),
            "planners": list(planners), "replayable": True, **extra}


def search(goal, query):
    return row(goal, ("web.search", {"query": query, "site": "youtube"}, f"Search YouTube for {query}"))


def installed(goal, query):
    return row(goal, ("apps.installed", {"query": query}, f"Check whether {query} is installed"))


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.runtime = create_runtime(self.base)

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def write(self, rows, turns=()):
        data = self.base / "data"
        data.mkdir(parents=True, exist_ok=True)
        (data / "experience.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        (data / "conversations.jsonl").write_text("".join(json.dumps(t) + "\n" for t in turns), encoding="utf-8")

    def compile(self):
        return reflex.compile_all(self.base, self.runtime.registry)

    def match(self, goal, apps=APPS):
        return reflex.match(self.base, goal, self.runtime, apps=apps)


class CompileTests(Base):
    def test_two_examples_make_one_skill_that_fills_a_new_request(self):
        self.write([search("search lofi beats on youtube in brave", "lofi beats"),
                    search("search arijit songs on youtube in brave", "arijit songs")])
        result = self.compile()
        self.assertEqual(result["added"], ["search {s0} on youtube in brave"], result)
        proposal, _id = self.match("please search Old Hindi Songs on youtube in brave")
        step = proposal["next_steps"][0]
        self.assertEqual((step["tool"], step["arguments"]), ("web.search", {"query": "Old Hindi Songs",
                                                                             "site": "youtube"}))
        self.assertEqual(step["purpose"], "Search YouTube for Old Hindi Songs")
        self.assertTrue(proposal["finish"])   # an R1 action: done when it is verified
        self.assertIsNone(self.match("search lofi on youtube in chrome"))   # the fixed words must all be there
        self.assertEqual(reflex.summary(self.base)["skills"][0]["phrase"], "search {query} on youtube in brave")

    def test_a_single_example_or_identical_wording_teaches_nothing(self):
        self.write([search("search lofi beats on youtube in brave", "lofi beats"),
                    search("Search lofi beats on YouTube in Brave!", "lofi beats")])
        self.assertEqual(self.compile()["added"], [])

    def test_leave_one_out_failure_blocks_the_skill(self):
        def two(goal, first, second):
            return row(goal, ("apps.installed", {"query": first}, "check"),
                       ("web.search", {"query": second, "site": "google"}, "search"))
        self.write([two("look up best pizza for kids for delhi", "best pizza for kids", "delhi"),
                    two("look up vlc for steam", "vlc", "steam")])
        result = self.compile()
        self.assertEqual(result["added"], [])
        self.assertIn("leave-one-out", result["rejected"][0]["reason"])

    def test_a_phrase_that_would_catch_a_request_done_with_other_tools_is_refused(self):
        turn = {"at": time.time(), "said": "search the news on youtube in brave", "status": "done",
                "tools": ["web.news"], "planners": ["local"]}
        self.write([search("search lofi beats on youtube in brave", "lofi beats"),
                    search("search arijit songs on youtube in brave", "arijit songs")], [turn])
        result = self.compile()
        self.assertEqual(result["added"], [])
        self.assertIn("would also catch", result["rejected"][0]["reason"])

    def test_messages_deletes_and_rule_matched_plans_are_never_compiled(self):
        self.write([row("ping mammi with hello there", ("message.send", {"app": "whatsapp", "to": "Mammi",
                                                                        "text": "hello there"}, "send")),
                    row("ping papa with good night", ("message.send", {"app": "whatsapp", "to": "Papa",
                                                                      "text": "good night"}, "send")),
                    row("bin the file a.txt now", ("filesystem.recycle", {"path": "a.txt"}, "recycle")),
                    row("bin the file b.txt now", ("filesystem.recycle", {"path": "b.txt"}, "recycle")),
                    installed("tell me whether vlc exists here", "vlc") | {"planners": ["quick"]},
                    installed("tell me whether steam exists here", "steam") | {"planners": ["quick"]},
                    installed("is zz1 there or not", "zz1") | {"rating": "bad"},
                    installed("is zz2 there or not", "zz2")])
        self.assertEqual(self.compile()["added"], [])

    def test_an_uninstalled_app_does_not_match(self):
        self.write([row("fire up Spotify for me right away", ("apps.launch", {"name": "Spotify"}, "Open Spotify")),
                    row("fire up Calculator for me right away", ("apps.launch", {"name": "Calculator"},
                                                                 "Open Calculator"))])
        self.assertEqual(len(self.compile()["added"]), 1)
        self.assertIsNone(self.match("fire up Zzunknown for me right away"))
        proposal, _id = self.match("fire up spotify for me right away")
        self.assertEqual(proposal["next_steps"][0]["arguments"], {"name": "Spotify"})   # the installed app's name

    def test_existing_skills_keep_their_state_when_compiled_again(self):
        self.write([search("search lofi beats on youtube in brave", "lofi beats"),
                    search("search arijit songs on youtube in brave", "arijit songs")])
        self.compile()
        skill = reflex.load(self.base)[0]
        reflex.set_enabled(self.base, skill["id"], False)
        self.compile()
        self.assertEqual(len(reflex.load(self.base)), 1)
        self.assertFalse(reflex.load(self.base)[0]["enabled"])


class DemotionTests(Base):
    def setUp(self):
        super().setUp()
        self.write([installed("tell me whether vlc exists on this laptop", "vlc"),
                    installed("tell me whether steam exists on this laptop", "steam")])
        self.compile()
        self.id = reflex.load(self.base)[0]["id"]

    def test_one_failure_switches_the_skill_off(self):
        self.assertIsNotNone(self.match("tell me whether zoom exists on this laptop"))
        reflex.feedback(self.base, self.id, True)
        reflex.feedback(self.base, self.id, False, "tell me whether zoom exists on this laptop")
        skill = reflex.load(self.base)[0]
        self.assertEqual((skill["hits"], skill["passes"], skill["fails"], skill["enabled"]), (2, 1, 1, False))
        self.assertIsNone(self.match("tell me whether zoom exists on this laptop"))

    def test_galat_kiya_switches_off_the_skill_that_planned_it(self):
        self.assertEqual(reflex.on_bad_rating(self.base, "tell me whether zoom exists on this laptop"), [self.id])
        self.assertFalse(reflex.load(self.base)[0]["enabled"])

    def test_a_step_that_keeps_failing_switches_the_skill_off(self):
        for verdict in ["FAIL", "FAIL", "FAIL", "PASS", "PASS"]:
            self.runtime.ledger.record("apps.installed", target_key("apps.installed", {"query": "zoom"}),
                                       expected="x", observed="y", verdict=verdict)
        self.assertIsNone(self.match("tell me whether zoom exists on this laptop"))
        self.assertFalse(reflex.load(self.base)[0]["enabled"])


class SessionTests(Base):
    def propose(self, goal):
        session = AgentSession(goal, mode="owner")
        session.quick = QuickPlanner()
        session.reflex = reflex.ReflexPlanner(self.base)
        with patch.object(session, "_checked", side_effect=AssertionError("the model must not be asked")):
            return session._propose(self.runtime, None, None, lambda: None)

    def test_a_learned_skill_plans_without_the_model_and_a_hand_rule_wins(self):
        goal = "tell me whether Zzqx exists on this laptop"
        self.assertIsNone(quick_proposal(goal))
        self.write([installed("tell me whether vlc exists on this laptop", "vlc"),
                    installed("tell me whether steam exists on this laptop", "steam")])
        self.compile()
        proposal, meta = self.propose(goal)
        self.assertEqual(meta["planner"], "reflex")
        self.assertTrue(meta["backend"].startswith("reflex:"))
        self.assertEqual(proposal["next_steps"][0]["arguments"], {"query": "Zzqx"})
        # A skill whose phrase also fits a hand-written rule never takes over from the rule.
        skills = reflex.load(self.base)
        skills[0]["regex"] = r"^what\s+(?P<s0>\S.{0,59}?)\s+is\s+it$"
        (self.base / "data" / "reflexes.json").write_text(json.dumps(skills), encoding="utf-8")
        self.assertIsNotNone(self.match("what time is it"))
        self.assertEqual(self.propose("what time is it")[1]["planner"], "quick")

    def test_after_session_counts_runs_and_compiles_new_shapes(self):
        class Done:
            def __init__(self, goal, planners, steps, status="done"):
                self.value = {"goal": goal, "status": status, "planners": planners, "steps": steps}

            def snapshot(self):
                return self.value

        self.write([installed("tell me whether vlc exists on this laptop", "vlc"),
                    installed("tell me whether steam exists on this laptop", "steam")])
        steps = [{"tool": "apps.installed", "arguments": {"query": "vlc"}, "state": "COMPLETED"}]
        result = reflex.after_session(self.base, Done("x", [{"planner": "local"}], steps), self.runtime, True)
        self.assertEqual(len(result["added"]), 1)
        skill_id = reflex.load(self.base)[0]["id"]
        backend = [{"planner": "reflex", "backend": "reflex:" + skill_id}]
        reflex.after_session(self.base, Done("y", backend, steps), self.runtime, True)
        reflex.after_session(self.base, Done("y", backend, steps, status="waiting_confirmation"), self.runtime, True)
        self.assertEqual(reflex.load(self.base)[0]["hits"], 1)   # a step still waiting is not a verdict
        reflex.after_session(self.base, Done("y", backend, [{**steps[0], "state": "FAILED"}], status="failed"),
                             self.runtime, True)
        self.assertFalse(reflex.load(self.base)[0]["enabled"])

    def test_instant_share_this_week_and_last(self):
        now = time.time()
        turns = [{"at": now - 3600, "said": "a", "planners": ["quick"]},
                 {"at": now - 7200, "said": "b", "planners": ["reflex", "local"]},
                 {"at": now - 8 * 86400, "said": "c", "planners": ["replay"]},
                 {"at": now - 60, "said": "d", "planners": []}]
        self.write([], turns)
        self.assertEqual(reflex.instant_share(self.base, now), (0.5, 1.0))


class ToolTests(Base):
    def test_what_did_you_learn_is_instant_and_lists_the_skills(self):
        from chutku import mind
        from chutku.quick_intents import _say_learned
        self.assertEqual(quick_proposal("tumne kya seekha")["next_steps"][0]["tool"], "reflex.list")
        self.assertEqual(quick_proposal("what did you learn?")["next_steps"][0]["tool"], "reflex.list")
        self.write([search("search lofi beats on youtube in brave", "lofi beats"),
                    search("search arijit songs on youtube in brave", "arijit songs")])
        self.compile()
        with patch.object(mind, "PROJECT_ROOT", self.base):
            result = self.runtime.run("reflex.list", {})
        self.assertEqual(result["state"], "COMPLETED")
        text = _say_learned(result["output"])
        self.assertIn("I learned 1 skill (1 on): \"search {query} on youtube in brave\" (0/0 worked).", text)


if __name__ == "__main__":
    unittest.main()

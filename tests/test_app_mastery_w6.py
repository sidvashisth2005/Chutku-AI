"""W6 A14 cross-app routines (desktop.do steps by element name), A15 teach mode, A16 screen survey.
All on a fake agent-desktop: the live checks need the owner's Windows PC."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chutku import routines
from chutku.apps import teach
from chutku.quick_intents import quick_proposal
from chutku.tools import desktop
from chutku.tools.registry import ToolRegistry, Verification
from test_desktop_d1 import FakeAgentDesktop, WINDOW


class Base(unittest.TestCase):
    def setUp(self):
        desktop._seen.clear(), desktop._latest.clear(), desktop._outlines.clear()
        self.fake = FakeAgentDesktop()
        for target, value in ((desktop, {"call": self.fake}),):
            patcher = mock.patch.multiple(target, **value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        store = mock.patch.object(routines, "store_path", return_value=Path(self.temp.name) / "routines.json")
        store.start()
        self.addCleanup(store.stop)
        self.registry = ToolRegistry()
        desktop.register_desktop_tools(self.registry)
        teach.register_teach_tools(self.registry)
        routines.register_routine_tools(self.registry)

    def run_tool(self, name, arguments):
        tool = self.registry.get(name)
        tool.validate_arguments(arguments)
        return tool.execute(arguments, None)


class DesktopDoTests(Base):
    def test_acts_on_the_element_named_without_a_prior_look(self):
        result = self.run_tool("desktop.do", {"app": "fixture", "name": "dark mode", "action": "toggle"})
        self.assertEqual(result.verification, Verification.PASS)
        self.assertIn(("toggle", "@sfake0001:e4"), [c[0] for c in self.fake.calls])
        result = self.run_tool("desktop.do", {"app": "fixture", "name": "Note", "action": "set_text", "text": "hi"})
        args, stdin = next(c for c in self.fake.calls if c[0][0] == "set-value")
        self.assertEqual((stdin, "hi" in args), ("hi", False))

    def test_consequential_names_are_refused_and_nothing_is_pressed(self):
        result = self.run_tool("desktop.do", {"app": "fixture", "name": "Send", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIn("desktop.act_risky", result.output["error"])
        self.assertFalse([c for c in self.fake.calls if c[0][0] == "click"])

    def test_a_missing_name_searches_then_fails(self):
        real = self.fake.__call__

        def with_find(*args, stdin=None):
            if args[0] == "find":
                self.fake.calls.append((args, stdin))
                return {"snapshot_id": "sfind01", "matches": []}
            return real(*args, stdin=stdin)
        desktop.call = with_find
        result = self.run_tool("desktop.do", {"app": "fixture", "name": "Lofi", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIn("No 'Lofi'", result.output["error"])
        self.assertIn("find", [c[0][0] for c in self.fake.calls])
        with self.assertRaises(ValueError):
            self.run_tool("desktop.do", {"app": "fixture", "name": "Note", "action": "set_text"})


class RoutineTests(Base):
    def test_a_routine_mixes_instant_commands_and_app_steps(self):
        saved = self.run_tool("routine.save", {"name": "study", "commands": [
            "set volume to 30", 'toggle "Dark mode" in fixture', 'type "chapter 4" into "Note" in fixture']})
        self.assertEqual(saved.verification, Verification.PASS, saved.output)
        steps = quick_proposal("study")["next_steps"]
        self.assertEqual([s["tool"] for s in steps], ["audio.volume", "desktop.do", "desktop.do"])
        self.assertEqual(steps[2]["arguments"], {"app": "fixture", "name": "Note", "action": "set_text",
                                                 "text": "chapter 4"})

    def test_unparsed_app_steps_are_refused_at_save(self):
        saved = self.run_tool("routine.save", {"name": "bad", "commands": ['delete "Inbox" in Outlook']})
        self.assertEqual(saved.verification, Verification.FAIL)
        self.assertIsNone(routines.command_steps('click "bad \\q" in Outlook'))


def window(note="", checked=False, password=""):
    return {"role": "window", "name": "Fixture", "children": [
        {"role": "textfield", "name": "Note", "value": note},
        {"role": "checkbox", "name": "Dark mode", "states": ["checked"] if checked else []},
        {"role": "textfield", "name": "Password", "value": password},
        {"role": "textfield", "name": "Code", "value": "●●●●" if password else ""},
        {"role": "statictext", "name": "Display", "value": note}]}


class TeachTests(Base):
    def test_what_the_owner_did_becomes_a_routine_that_replays(self):
        reads = iter([window(), window("h"), window("hello"), window("hello", checked=True, password="hunter2")])
        teacher = teach.Teacher("fixture", "notes setup", read=lambda: teach.read_tree(next(reads)))
        teacher.before = teacher.read()
        teacher.poll(), teacher.poll()
        name, commands = teacher.stop()
        self.assertEqual(commands, ['type "hello" into "Note" in fixture', 'toggle "Dark mode" in fixture'])
        stored = " ".join(routines.load()[name])
        self.assertNotIn("hunter2", stored)            # a secret field is never recorded
        self.assertNotIn("Password", stored)
        self.assertNotIn("Code", stored)               # a masked field neither
        steps = routines.steps_for(name)
        self.assertEqual([s["arguments"]["action"] for s in steps], ["set_text", "toggle"])
        self.run_tool("desktop.do", steps[1]["arguments"])
        self.assertTrue(self.fake.checked)

    def test_nothing_shown_saves_nothing(self):
        teacher = teach.Teacher("fixture", "empty", read=lambda: teach.read_tree(window()))
        teacher.before = teacher.read()
        with self.assertRaises(ValueError):
            teacher.stop()
        self.assertEqual(routines.load(), {})

    def test_the_tools_and_phrases(self):
        self.assertIsNone(quick_proposal("ho gaya"))              # not teaching: "ho gaya" is not hijacked
        started = self.run_tool("teach.start", {"app": "fixture", "name": "dark"})
        self.addCleanup(lambda: teach._session.update(teacher=None))
        self.assertEqual(started.verification, Verification.PASS, started.output)
        self.assertEqual(self.run_tool("teach.start", {"app": "fixture", "name": "x"}).verification, Verification.FAIL)
        self.assertEqual(quick_proposal("ho gaya")["next_steps"][0]["tool"], "teach.stop")
        self.fake.checked = True
        done = self.run_tool("teach.stop", {})
        self.assertEqual(done.verification, Verification.PASS, done.output)
        self.assertEqual(done.output["commands"], ['toggle "Dark mode" in fixture'])
        self.assertFalse(teach.teaching())
        self.assertEqual(self.run_tool("teach.stop", {}).verification, Verification.FAIL)
        self.assertEqual(self.run_tool("teach.start", {"app": "photoshop", "name": "x"}).verification,
                         Verification.FAIL)
        self.assertFalse(teach.teaching())


class InstantReplyTests(unittest.TestCase):
    def test_teach_and_survey_answer_without_the_model(self):
        import json
        from types import SimpleNamespace
        from chutku.quick_intents import quick_answer
        for goal, tool in (("ho gaya", "teach.stop"), ("screen survey karo", "desktop.survey"),
                           ("sikho dark setup settings mein", "teach.start")):
            session = SimpleNamespace(goal=goal, steps=[{"tool": tool, "state": "COMPLETED", "purpose": "p",
                                                          "observation": json.dumps({"summary": "S " + tool})}])
            self.assertEqual(quick_answer(session), "S " + tool)   # "ho gaya": teaching already ended, still answered
        failed = SimpleNamespace(goal="ho gaya", steps=[{"tool": "teach.stop", "state": "FAILED", "purpose": "p",
                                                         "observation": "{}"}])
        self.assertIsNone(quick_answer(failed))


class SurveyTests(Base):
    def test_survey_summarizes_visible_windows_from_skeletons(self):
        result = self.run_tool("desktop.survey", {})
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual([w["title"] for w in result.output["windows"]], ["ChutkuFormFixture", "Other"])
        self.assertIn("Fixture.exe: ChutkuFormFixture", result.output["summary"])
        snapshots = [c[0] for c in self.fake.calls if c[0][0] == "snapshot"]
        self.assertTrue(snapshots and all("--skeleton" in args for args in snapshots))
        self.assertFalse([c for c in self.fake.calls if c[0][0] not in {"list-windows", "snapshot"}])   # read only
        self.assertEqual(quick_proposal("screen survey karo")["next_steps"][0]["tool"], "desktop.survey")


if __name__ == "__main__":
    unittest.main()

"""D1: background desktop control through agent-desktop (desktop.look / desktop.act / desktop.act_risky)."""
import time
import unittest
from unittest import mock

from chutku.tools import desktop
from chutku.tools.registry import Risk, ToolRegistry, Verification

WINDOW = {"id": "w-1", "app_name": "Fixture.exe", "title": "ChutkuFormFixture", "visible": True,
          "minimized": False, "is_focused": False}


def tree(snapshot, checked=False):
    return {"snapshot_id": snapshot, "tree": {"role": "window", "name": "ChutkuFormFixture", "children": [
        {"ref_id": f"@{snapshot}:e1", "role": "textfield", "name": "Note", "available_actions": ["SetValue", "SetFocus"]},
        {"ref_id": f"@{snapshot}:e2", "role": "button", "name": "Seven", "available_actions": ["Click", "SetFocus"]},
        {"ref_id": f"@{snapshot}:e3", "role": "button", "name": "Send", "available_actions": ["Click"]},
        {"ref_id": f"@{snapshot}:e4", "role": "checkbox", "name": "Dark mode", "available_actions": ["Toggle"],
         "states": ["checked"] if checked else []},
        {"role": "statictext", "name": "Display", "value": "77"}]}}


class FakeAgentDesktop:
    """Answers like the real CLI; records every argv and stdin."""

    def __init__(self):
        self.calls, self.snapshots, self.checked, self.huge = [], 0, False, False

    def __call__(self, *args, stdin=None):
        self.calls.append((args, stdin))
        if args[0] == "list-windows":
            return [WINDOW, {**WINDOW, "id": "w-2", "app_name": "Other.exe", "title": "Other"}]
        if args[0] == "snapshot":
            self.snapshots += 1
            snapshot = tree(f"sfake{self.snapshots:04d}", self.checked)
            if self.huge and "--skeleton" not in args:
                snapshot["tree"]["children"] *= 40
            return snapshot
        if args[0] == "toggle":
            self.checked = True
            return {"disposition": {"delivery": "delivered_verified"}}
        if args[0] in desktop.VERBS.values():
            return {"disposition": {"delivery": "delivered_unverified"}}
        raise AssertionError(args)


class DesktopToolsTest(unittest.TestCase):
    def setUp(self):
        desktop._seen.clear(), desktop._latest.clear(), desktop._outlines.clear()
        self.fake = FakeAgentDesktop()
        patcher = mock.patch.object(desktop, "call", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = ToolRegistry()
        desktop.register_desktop_tools(self.registry)

    def run_tool(self, name, arguments):
        tool = self.registry.get(name)
        tool.validate_arguments(arguments)
        return tool.execute(arguments, None)

    def test_look_lists_refs_and_text_by_app_name(self):
        result = self.run_tool("desktop.look", {"app": "fixture"})
        self.assertEqual(result.verification, Verification.PASS)
        lines = result.output["elements"]
        self.assertIn(' e2 button "Seven" [click]', lines)
        self.assertTrue(any('statictext "Display" ="77"' in line for line in lines))
        self.assertEqual(result.output["window"], "ChutkuFormFixture")
        self.assertEqual(result.output["provenance"], "external_untrusted")
        self.assertIn(("snapshot", "--window-id", "w-1", "--compact", "--timeout-ms", "8000"),
                      [c[0] for c in self.fake.calls])

    def test_a_window_too_big_comes_back_as_a_skeleton(self):
        self.fake.huge = True
        result = self.run_tool("desktop.look", {"app": "fixture"})
        self.assertEqual(self.fake.calls[-1][0][-1], "--skeleton")
        self.assertLessEqual(len(result.output["elements"]), desktop.MAX_LINES)
        self.assertNotIn("truncated", result.output)

    def test_title_words_pick_a_window_and_unknown_app_fails(self):
        self.assertEqual(self.run_tool("desktop.look", {"app": "Other"}).output["window"], "Other")
        result = self.run_tool("desktop.look", {"app": "photoshop"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIn("No open window", result.output["error"])

    def test_click_by_short_ref_returns_new_state(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        result = self.run_tool("desktop.act", {"ref": "e2", "action": "click"})
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual(self.fake.calls[-2][0], ("click", "@sfake0001:e2"))
        self.assertEqual(result.output["snapshot"], "sfake0002")
        self.assertFalse(result.output["changed"])

    def test_toggle_reports_the_change(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        result = self.run_tool("desktop.act", {"ref": "e4", "action": "toggle"})
        self.assertEqual(result.output["delivery"], "delivered_verified")
        self.assertTrue(result.output["changed"])
        self.assertIn('e4 checkbox "Dark mode" [toggle] {checked}', " ".join(result.output["elements"]))

    def test_set_text_goes_through_stdin_never_argv(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        self.run_tool("desktop.act", {"ref": "e1", "action": "set_text", "text": "secret नमस्ते"})
        args, stdin = next(c for c in self.fake.calls if c[0][0] == "set-value")
        self.assertEqual(stdin, "secret नमस्ते")
        self.assertNotIn("secret नमस्ते", " ".join(args))

    def test_never_headed(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        for arguments in ({"ref": "e2", "action": "click"}, {"ref": "e4", "action": "toggle"},
                          {"ref": "e1", "action": "scroll", "direction": "down", "amount": 2}):
            self.run_tool("desktop.act", arguments)
        self.assertFalse([c for c in self.fake.calls if "--headed" in c[0]])

    def test_invented_ref_is_refused(self):
        result = self.run_tool("desktop.act", {"ref": "e2", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIn("not from a recent desktop.look", result.output["error"])
        self.run_tool("desktop.look", {"app": "fixture"})
        result = self.run_tool("desktop.act", {"ref": "e99", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertFalse([c for c in self.fake.calls if c[0][0] == "click"])

    def test_old_ref_expires(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        with mock.patch.object(desktop.time, "monotonic", return_value=time.monotonic() + desktop.ELEMENT_SECONDS + 1):
            result = self.run_tool("desktop.act", {"ref": "e2", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)

    def test_send_needs_the_risky_tool_and_its_label(self):
        self.run_tool("desktop.look", {"app": "fixture"})
        refused = self.run_tool("desktop.act", {"ref": "e3", "action": "click"})
        self.assertEqual(refused.verification, Verification.FAIL)
        self.assertIn("desktop.act_risky", refused.output["error"])
        with self.assertRaisesRegex(ValueError, "'Seven', not 'Send'"):   # refused before any approval card
            self.run_tool("desktop.act_risky", {"ref": "e2", "action": "click", "label": "Send"})
        self.assertFalse([c for c in self.fake.calls if c[0][0] == "click"])
        self.assertEqual(desktop.describe({"ref": "e3", "label": "Send"}), '"Send" in ChutkuFormFixture')
        done = self.run_tool("desktop.act_risky", {"ref": "e3", "action": "click", "label": "Send"})
        self.assertEqual(done.verification, Verification.PASS)

    def test_risk_levels_and_validation(self):
        self.assertEqual(self.registry.get("desktop.look").base_risk, Risk.OBSERVATION)
        self.assertEqual(self.registry.get("desktop.act").base_risk, Risk.REVERSIBLE)
        self.assertEqual(self.registry.get("desktop.act_risky").base_risk, Risk.EXTERNAL_SIDE_EFFECT)
        self.assertIn("text", self.registry.get("desktop.act").sensitive_argument_names)
        for bad in ({"ref": "click e2", "action": "click"}, {"ref": "e2", "action": "rm"},
                    {"ref": "e2", "action": "set_text"}):
            with self.assertRaises(ValueError):
                self.registry.get("desktop.act").validate_arguments(bad)

    def test_missing_binary_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {"CHUTKU_AGENT_DESKTOP": ""}), \
                mock.patch.object(desktop, "ROOT", desktop.Path("Z:/nowhere")), \
                mock.patch.object(desktop.shutil, "which", return_value=None):
            with self.assertRaisesRegex(OSError, "npm ci --prefix tools"):
                desktop.binary()


class RiskyAsksInEveryModeTest(unittest.TestCase):
    def test_step_question_for_desktop_act_risky_only(self):
        from chutku.runtime import Runtime as ChutkuRuntime
        registry = ToolRegistry()
        desktop.register_desktop_tools(registry)
        runtime = ChutkuRuntime.__new__(ChutkuRuntime)
        question = ChutkuRuntime.step_question(runtime, registry.get("desktop.act_risky"),
                                               {"ref": "e3", "action": "click", "label": "Send"})
        self.assertIn('"Send"', question)
        self.assertIsNone(ChutkuRuntime.step_question(runtime, registry.get("desktop.act"),
                                                      {"ref": "e2", "action": "click"}))


if __name__ == "__main__":
    unittest.main()

"""Taint and identity hardening (master plan S2, audit 2026-10-06)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import agent_loop as loop
from chutku import mind, vision
from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.policy.kernel import Decision
from chutku.tools import desktop_controls, free_input, screen_vision
from chutku.tools.registry import ExecutionContext, Verification


class TaintV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.foreground = patch.object(free_input, "_foreground", return_value=(
            None, {"executable": "C:/Windows/notepad.exe", "title": "Untitled - Notepad"}, "notepad.exe"))
        self.foreground.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")

    def tearDown(self):
        self.runtime.close()
        self.foreground.stop()
        self.mind_root.stop()
        self.temp.cleanup()

    def decide(self, name, arguments=None, *, tainted=False, mode="owner"):
        tool = self.runtime.registry.get(name)
        arguments = arguments or {}
        return self.runtime.policy.authorize(
            tool, arguments, provenance="delegated", resource_access=frozenset({"observe", "modify"}),
            capability_allowed=True, autonomy=mode, tainted=tainted, exposed=tainted,
            owner_question=self.runtime.step_question(tool, arguments)).decision

    def test_every_taint_and_privacy_name_is_a_real_tool(self):
        names = {tool.name for tool in self.runtime.registry.list()}
        for group in (loop.TAINTING_TOOLS, loop.PRIVATE_TOOLS, loop.READ_TOOLS):
            self.assertEqual(set(group) - names, set())   # a stale name silently disables the rule

    def test_clipboard_and_image_text_taint_the_session(self):
        for name in ("clipboard.read_text", "image.describe", "screen.click"):
            session = AgentSession("do it", mode="owner")
            session._record({"tool": name, "arguments": {}, "purpose": "x"}, {"state": "COMPLETED", "output": {}})
            self.assertTrue(session.tainted, name)

    def test_tainted_r1_steps_that_start_or_remember_things_ask(self):
        for name in ("mind.person", "settings.offline_mode", "task.schedule"):   # a page must never plant these
            self.assertEqual(self.decide(name, tainted=True), Decision.CONFIRM, name)
        for name in ("apps.launch", "files.open"):   # owner order 2026-10-08: opening needs no ask in owner mode
            self.assertEqual(self.decide(name, tainted=True), Decision.ALLOW, name)
        for mode in ("auto_safe", "auto_edits"):
            self.assertEqual(self.decide("apps.launch", tainted=True, mode=mode), Decision.CONFIRM, mode)
        self.assertEqual(self.decide("apps.launch"), Decision.ALLOW)                 # untainted: unchanged
        self.assertEqual(self.decide("system.get_time", tainted=True), Decision.ALLOW)  # reading stays automatic
        tool = self.runtime.registry.get("youtube.play")    # navigation after public web content stays automatic
        self.assertEqual(self.runtime.policy.authorize(tool, {}, provenance="delegated", capability_allowed=True,
                                                       autonomy="owner", tainted=True, exposed=False).decision,
                         Decision.ALLOW)

    def test_changing_a_saved_contact_asks(self):
        mind.default().remember_person("AK", aliases=["mammi"], phone="+919876543210", whatsapp="Ak")
        self.assertEqual(self.decide("mind.person", {"name": "AK", "phone": "+911111111111"}), Decision.CONFIRM)
        self.assertEqual(self.decide("mind.person", {"name": "AK", "whatsapp": "Someone Else"}), Decision.CONFIRM)
        self.assertEqual(self.decide("mind.person", {"name": "AK", "phone": "+91 98765 43210"}), Decision.ALLOW)
        self.assertEqual(self.decide("mind.person", {"name": "AK", "aliases": ["maa"]}), Decision.ALLOW)
        self.assertEqual(self.decide("mind.person", {"name": "Ravi", "phone": "+912222222222"}), Decision.ALLOW)

    def test_changing_a_saved_contact_note_asks(self):
        self.runtime.memory.save("contact_ravi", "+912222222222")
        self.assertEqual(self.decide("memory.remember", {"key": "contact_ravi", "value": "+913333333333"}),
                         Decision.CONFIRM)

    def test_short_words_do_not_count_as_the_owners_words(self):
        session = AgentSession("send hi to mammi and open youtube.com", mode="owner")
        self.assertFalse(session._from_owner_words({"arguments": {"text": "hi"}}))
        self.assertTrue(session._from_owner_words({"arguments": {"text": "youtube.com"}}))
        self.assertFalse(session._from_owner_words({"arguments": {"text": "tube"}}))  # inside a word

    def test_win_r_keys_and_approve_clicks_ask(self):
        self.assertEqual(self.decide("keyboard.keys", {"keys": "win+r"}), Decision.CONFIRM)
        self.assertEqual(self.decide("keyboard.keys", {"keys": "ctrl+shift+t"}), Decision.ALLOW)
        self.assertEqual(self.decide("mouse.click", {"text": "Approve"}), Decision.CONFIRM)


class ScreenClickBindingTests(unittest.TestCase):
    def setUp(self):
        self.context = ExecutionContext("t", None, Path("."))
        shot = type("Shot", (), {"window": "w"})()
        vision.remember_seen(shot, [{"id": "e3", "label": "Send", "kind": "button", "rect": (10, 10, 50, 30)}])

    def tearDown(self):
        vision._state["seen"] = None   # never leave fake screen elements behind for other tests

    def test_risky_click_needs_the_label(self):
        with self.assertRaises(ValueError):
            screen_vision._validate_risky_click({"element": "e3"})
        screen_vision._validate_risky_click({"element": "e3", "label": "Send"})

    def test_click_refused_when_the_element_changed(self):
        with patch.object(desktop_controls, "own_window_at", return_value=False):
            result = screen_vision._click({"element": "e3", "label": "Delete all"}, self.context, risky_allowed=True)
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIn("read again", result.output["error"])

    def test_never_clicks_chutkus_own_window(self):
        with patch.object(desktop_controls, "own_window_at", return_value=True), \
                patch.object(vision, "click_at") as clicked:
            result = screen_vision._click({"element": "e3", "label": "Send"}, self.context, risky_allowed=True)
        self.assertEqual(result.verification, Verification.FAIL)
        clicked.assert_not_called()
        with patch.object(desktop_controls, "own_window_at", return_value=True), \
                patch.object(free_input, "_point", return_value=(5, 5, "Approve")), \
                patch.object(vision, "click_at") as clicked:
            result = free_input._click({"x": 5, "y": 5}, self.context)
        self.assertEqual(result.verification, Verification.FAIL)
        clicked.assert_not_called()

    def test_own_window_detection(self):
        page = {"executable": "C:/x/brave.exe", "title": "Chutku - Brave"}
        self.assertTrue(desktop_controls.is_own_window(page))
        self.assertTrue(desktop_controls.is_own_window({"executable": "C:/x/pythonw.exe", "title": "Chutku HUD"}))
        self.assertFalse(desktop_controls.is_own_window({"executable": "C:/x/brave.exe", "title": "YouTube"}))


if __name__ == "__main__":
    unittest.main()

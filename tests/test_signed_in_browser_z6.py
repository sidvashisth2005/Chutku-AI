"""Z6: the owner's signed-in browser through agent-browser (browser.look / browser.act / browser.act_risky / login)."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from chutku.tools import signed_in_browser as sib
from chutku.tools.registry import Risk, ToolRegistry, Verification

PAGE = {"snapshot": '- link "Inbox (3)" [ref=e1]\n- button "Send" [ref=e2]\n- textbox "To" [ref=e3]\n'
                    '- link "Delete all spam" [ref=e4]',
        "refs": {"e1": {"name": "Inbox (3)", "role": "link"}, "e2": {"name": "Send", "role": "button"},
                 "e3": {"name": "To", "role": "textbox"}, "e4": {"name": "Delete all spam", "role": "link"}}}


class FakeBrowser:
    def __init__(self):
        self.batches = []

    def __call__(self, commands):
        self.batches.append(commands)
        answers = {"snapshot": PAGE, "get": None, "open": {"url": "https://mail.google.com/"}}
        out = []
        for command in commands:
            if command[0] == "get":
                out.append({"url": "https://mail.google.com/mail/u/0/"} if command[1] == "url" else {"title": "Inbox"})
            else:
                out.append(answers.get(command[0], {}))
        return out

    def commands(self):
        return [c for batch in self.batches for c in batch]


class SignedInBrowserTest(unittest.TestCase):
    def setUp(self):
        sib._refs.update({"at": 0.0, "map": {}, "url": ""})
        self.fake = FakeBrowser()
        patcher = mock.patch.object(sib, "run", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = ToolRegistry()
        sib.register_signed_in_browser_tools(self.registry)

    def use(self, name, arguments):
        tool = self.registry.get(name)
        tool.validate_arguments(arguments)
        return tool.execute(arguments, None)

    def test_look_opens_and_lists_refs_as_untrusted(self):
        result = self.use("browser.look", {"url": "https://mail.google.com"})
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual(self.fake.batches[0], [["open", "https://mail.google.com"]])
        self.assertEqual(result.output["title"], "Inbox")
        self.assertIn('- link "Inbox (3)" [ref=e1]', result.output["elements"])
        self.assertEqual(result.output["provenance"], "external_untrusted")

    def test_find_narrows_a_big_page(self):
        result = self.use("browser.look", {"find": "inbox"})
        self.assertEqual(result.output["elements"], ['- link "Inbox (3)" [ref=e1]'])

    def test_click_reads_the_new_page_and_waits_for_navigation(self):
        self.use("browser.look", {})
        result = self.use("browser.act", {"ref": "e1", "action": "click"})
        self.assertEqual(result.verification, Verification.PASS)
        click, wait = self.fake.batches[-2]
        self.assertEqual(click, ["click", "@e1"])
        self.assertEqual(wait[:2], ["wait", "--fn"])
        self.assertIn("location.href !==", wait[2])

    def test_invented_or_stale_ref_is_refused(self):
        result = self.use("browser.act", {"ref": "e1", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.use("browser.look", {})
        result = self.use("browser.act", {"ref": "e77", "action": "click"})
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertFalse([c for c in self.fake.commands() if c[0] == "click"])

    def test_send_and_delete_need_the_risky_tool_with_the_right_label(self):
        self.use("browser.look", {})
        for ref in ("e2", "e4"):
            refused = self.use("browser.act", {"ref": ref, "action": "click"})
            self.assertIn("browser.act_risky", refused.output["error"])
        with self.assertRaisesRegex(ValueError, "'Inbox \\(3\\)', not 'Send'"):
            self.use("browser.act_risky", {"ref": "e1", "action": "click", "label": "Send"})
        self.assertFalse([c for c in self.fake.commands() if c[0] == "click"])
        self.assertEqual(self.use("browser.act_risky", {"ref": "e2", "action": "click", "label": "Send"}).verification,
                         Verification.PASS)

    def test_fill_is_allowed_and_text_is_sensitive(self):
        self.use("browser.look", {})
        self.use("browser.type", {"ref": "e3", "action": "fill", "text": "mummy@example.com"})
        self.assertIn(["fill", "@e3", "mummy@example.com"], self.fake.commands())
        self.assertIn("text", self.registry.get("browser.type").sensitive_argument_names)
        with self.assertRaises(ValueError):   # typing is not a click
            self.registry.get("browser.act").validate_arguments({"ref": "e3", "action": "fill", "text": "x"})

    def test_validation(self):
        look, act, type_ = (self.registry.get(n) for n in ("browser.look", "browser.act", "browser.type"))
        for bad in ({"url": "file:///C:/Users"}, {"url": "javascript:alert(1)"}, {"url": "https://u:p@site.com"}):
            with self.assertRaises(ValueError):
                look.validate_arguments(bad)
        for bad in ({"action": "click"}, {"ref": "e1", "action": "eval"}):
            with self.assertRaises(ValueError):
                act.validate_arguments(bad)
        for bad in ({"ref": "e1", "action": "fill"}, {"action": "press", "key": "Enter; rm"}):
            with self.assertRaises(ValueError):
                type_.validate_arguments(bad)
        type_.validate_arguments({"action": "press", "key": "Control+a"})

    def test_risk_levels(self):
        self.assertEqual(self.registry.get("browser.look").base_risk, Risk.OBSERVATION)
        self.assertEqual(self.registry.get("browser.act").base_risk, Risk.REVERSIBLE)
        self.assertEqual(self.registry.get("browser.act_risky").base_risk, Risk.EXTERNAL_SIDE_EFFECT)
        # typing can carry text off the PC (asks after private data was read); clicking what the page offers cannot
        self.assertTrue(all(self.registry.get(n).network_egress for n in ("browser.look", "browser.type")))
        self.assertFalse(self.registry.get("browser.act").network_egress)


class RunTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.profile = Path(folder.name) / "browser-profile"

    def test_text_goes_through_stdin_and_output_to_a_file(self):
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(args=args, **kwargs)
            kwargs["stdout"].write(json.dumps([{"success": True, "result": {"clicked": "@e3"}}]).encode())
            return mock.Mock(returncode=0)
        with mock.patch.object(sib, "binary", return_value="ab.exe"), \
                mock.patch.object(sib, "browser_exe", return_value="brave.exe"), \
                mock.patch.object(sib.sys, "platform", "win32"), \
                mock.patch.object(sib, "PROFILE", self.profile), mock.patch.object(sib.subprocess, "run", fake_run):
            self.assertEqual(sib.run([["fill", "@e3", "secret"]]), [{"clicked": "@e3"}])
        self.assertNotIn("secret", " ".join(captured["args"]))
        self.assertIn(b"secret", captured["input"])
        self.assertNotEqual(captured["stdout"], sib.subprocess.PIPE)
        self.assertEqual(captured["env"]["AGENT_BROWSER_PROFILE"], str(self.profile))
        self.assertEqual(captured["env"]["AGENT_BROWSER_EXECUTABLE_PATH"], "brave.exe")

    def test_a_failed_command_raises(self):
        def fake_run(args, **kwargs):
            kwargs["stdout"].write(json.dumps([{"success": False, "error": "Element not found"}]).encode())
            return mock.Mock(returncode=1)
        with mock.patch.object(sib, "binary", return_value="ab.exe"), \
                mock.patch.object(sib, "browser_exe", return_value="brave.exe"), \
                mock.patch.object(sib.sys, "platform", "win32"), \
                mock.patch.object(sib, "PROFILE", self.profile), mock.patch.object(sib.subprocess, "run", fake_run):
            with self.assertRaisesRegex(OSError, "Element not found"):
                sib.run([["click", "@e9"]])

    def test_login_opens_a_plain_browser_without_automation(self):
        with mock.patch.object(sib, "run") as close, mock.patch.object(sib, "browser_exe", return_value="brave.exe"), \
                mock.patch.object(sib, "PROFILE", self.profile), mock.patch.object(sib.subprocess, "Popen") as popen:
            sib.login("https://accounts.google.com")
        close.assert_called_once_with([["close"]])
        args = popen.call_args[0][0]
        self.assertIn(f"--user-data-dir={self.profile}", args)
        self.assertFalse([a for a in args if "remote-debugging" in a])


class AsksFirstTest(unittest.TestCase):
    def setUp(self):
        from chutku.runtime import Runtime
        self.runtime = Runtime.__new__(Runtime)
        self.registry = ToolRegistry()
        sib.register_signed_in_browser_tools(self.registry)

    def question(self, name, arguments):
        from chutku.runtime import Runtime
        return Runtime.step_question(self.runtime, self.registry.get(name), arguments)

    def test_risky_asks_and_local_addresses_ask(self):
        self.assertIn('"Send"', self.question("browser.act_risky", {"ref": "e2", "action": "click", "label": "Send"}))
        self.assertIn("home network", self.question("browser.look", {"url": "http://192.168.1.1/admin"}))
        self.assertIsNone(self.question("browser.act", {"ref": "e1", "action": "click"}))


if __name__ == "__main__":
    unittest.main()

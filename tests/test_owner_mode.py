"""Owner mode (the owner's standing order of 2026-10-04): no approvals except file changes and deletions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.policy.kernel import Decision


class OwnerModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def decide(self, name, arguments=None, *, tainted=False):
        tool = self.runtime.registry.get(name)
        return self.runtime.policy.authorize(
            tool, arguments or {}, provenance="delegated", resource_access=frozenset({"observe", "modify"}),
            capability_allowed=True, autonomy="owner", tainted=tainted, exposed=tainted,
            owner_question=self.runtime.owner_question(tool, arguments or {})).decision

    def test_everyday_actions_run_without_asking(self):
        for name in ("apps.launch", "apps.quit", "apps.close", "windows.close", "keyboard.type_text", "keyboard.press_enter",
                     "input.click", "browser.workflow", "code.run_python", "code.build_project", "files.zip",
                     "filesystem.create_directory", "settings.theme_set", "system.volume_set", "reminder.set",
                     "mind.person", "note.add", "youtube.play"):
            self.assertEqual(self.decide(name), Decision.ALLOW, name)

    def test_file_changes_and_every_deletion_still_ask(self):
        for name in ("filesystem.write_text", "filesystem.move", "filesystem.copy", "files.organize", "log.undo",
                     "filesystem.undo_last_write", "filesystem.recycle", "memory.forget", "routine.forget", "mind.forget"):
            self.assertEqual(self.decide(name), Decision.CONFIRM, name)

    def test_power_kill_and_network_off_still_ask(self):
        for name in ("power.schedule", "process.terminate", "network.adapter_set"):
            self.assertEqual(self.decide(name), Decision.CONFIRM, name)

    def test_permanent_delete_is_never_chosen_by_the_agent(self):
        self.assertEqual(self.decide("filesystem.delete_permanent"), Decision.DENY)

    def test_messages_go_out_only_to_people_in_memory(self):
        send = {"app": "whatsapp", "to": "mammi", "text": "hi"}
        self.assertEqual(self.decide("message.send", send), Decision.CONFIRM)        # nobody saved yet
        mind.default().remember_person("UB", aliases=["mammi"])
        self.assertEqual(self.decide("message.send", send), Decision.ALLOW)
        self.assertEqual(self.decide("message.send", send | {"to": "UB"}), Decision.ALLOW)
        self.assertEqual(self.decide("message.send", send | {"to": "Rahul"}), Decision.CONFIRM)
        self.assertEqual(self.decide("message.send", send | {"to": "+919999999999"}), Decision.CONFIRM)  # new number
        # After reading a web page or a message, even a known person needs a click (prompt-injection guard).
        self.assertEqual(self.decide("message.send", send, tainted=True), Decision.CONFIRM)

    def test_saved_contact_numbers_count_as_known(self):
        self.runtime.memory.save("contact_ravi", "+919888888888")
        self.assertEqual(self.decide("message.send", {"app": "whatsapp", "to": "ravi", "text": "hi"}), Decision.ALLOW)

    def test_hard_limits_do_not_move(self):
        tool = self.runtime.registry.get("apps.launch")
        no_capability = self.runtime.policy.authorize(tool, {}, provenance="delegated", capability_allowed=False,
                                                      autonomy="owner")
        self.assertEqual(no_capability.decision, Decision.DENY)
        protected = self.runtime.policy.authorize(self.runtime.registry.get("files.zip"), {}, provenance="delegated",
                                                  resource_access=frozenset({"observe", "modify"}),
                                                  capability_allowed=True, autonomy="owner",
                                                  protected_reason="Windows system folder")
        self.assertEqual(protected.decision, Decision.DENY)
        other_modes = self.runtime.policy.authorize(self.runtime.registry.get("apps.quit"), {}, provenance="delegated",
                                                    capability_allowed=True, autonomy="auto_safe")
        self.assertEqual(other_modes.decision, Decision.CONFIRM)   # the old modes are unchanged

    def test_owner_is_the_default_hands_free_mode(self):
        from chutku.core.preferences import DEFAULTS, Preferences
        self.assertEqual(DEFAULTS["handsfree_mode"], "owner")
        prefs = Preferences(Path(self.temp.name) / "prefs")
        self.assertEqual(prefs.load()["handsfree_mode"], "owner")


if __name__ == "__main__":
    unittest.main()

"""W1 finding 3: a backup restore never brings back security state (pairings, grants, never-rules, approved skills)
unless the owner opts in with --include-security and types YES."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import backup

SECURITY = {"telegram.json": '{"chat_id": 666}', "remote.json": '{"devices": ["attacker"]}',
            "never_rules.json": "[]", "capability_grants.db": "grants", "resource_grants.db": "roots",
            "skills/approved.json": '{"evil": {"sha256": "x"}}', "skills/evil/tool.py": "import os"}
NORMAL = {"mind.json": '{"facts": {"name": "Asha"}}', "notes.json": "[]",
          "skills/_pending/draft/tool.py": "print(1)", "skills/_procedures/how/SKILL.md": "# how"}


class RestoreSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "install"
        self.folder = Path(self.temp.name) / "backups"
        self.write({**SECURITY, **NORMAL})
        self.zip = backup.create(self.base, folder=self.folder)["path"]
        # the current, safer state: Telegram unpaired, the evil skill removed, a rule added
        (self.data / "telegram.json").write_text("{}", encoding="utf-8")
        (self.data / "skills" / "approved.json").write_text("{}", encoding="utf-8")
        (self.data / "skills" / "evil" / "tool.py").unlink()
        (self.data / "never_rules.json").write_text('[{"kind": "path"}]', encoding="utf-8")
        (self.data / "mind.json").write_text("{}", encoding="utf-8")

    @property
    def data(self):
        return self.base / "data"

    def write(self, files):
        for relative, text in files.items():
            path = self.data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def test_the_classifier(self):
        for relative in SECURITY:
            self.assertTrue(backup.is_security_state(relative), relative)
        for relative in NORMAL:
            self.assertFalse(backup.is_security_state(relative), relative)
        self.assertTrue(backup.is_security_state("skills\\evil\\skill.json"))   # Windows separators too

    def test_case_and_trailing_dots_do_not_slip_past(self):
        # W8 security review: NTFS is case-insensitive and drops trailing dots/spaces, so these overwrite the real files
        for name in ("Never_Rules.json", "Capability_Grants.db", "telegram.json.", "Skills/approved.json",
                     "Skills/evil/tool.py", "SKILLS/evil /tool.py", "Remote.JSON "):
            self.assertTrue(backup.is_security_state(name), name)
        self.assertFalse(backup.is_security_state("Mind.json"))

    def test_restore_skips_security_state_and_lists_it(self):
        out = backup.restore(self.base, self.zip, folder=self.folder)
        self.assertEqual(set(out["skipped_security"]), set(SECURITY))
        self.assertEqual((self.data / "telegram.json").read_text(), "{}")              # not re-paired
        self.assertEqual((self.data / "skills" / "approved.json").read_text(), "{}")   # not re-approved
        self.assertFalse((self.data / "skills" / "evil" / "tool.py").exists())         # not brought back
        self.assertEqual((self.data / "never_rules.json").read_text(), '[{"kind": "path"}]')
        self.assertEqual(json.loads((self.data / "mind.json").read_text())["facts"]["name"], "Asha")   # memory: yes
        self.assertTrue((self.data / "skills" / "_pending" / "draft" / "tool.py").exists())

    def test_include_security_restores_everything(self):
        out = backup.restore(self.base, self.zip, folder=self.folder, include_security=True)
        self.assertEqual(out["skipped_security"], [])
        self.assertEqual((self.data / "telegram.json").read_text(), '{"chat_id": 666}')

    def test_the_cli_asks_and_a_wrong_answer_restores_without_security(self):
        from chutku import cli
        with patch("chutku.app.PROJECT_ROOT", self.base), patch("builtins.input", return_value="yes please"), \
                patch("chutku.backup.backup_folder", return_value=self.folder), patch("builtins.print"):
            with patch("sys.argv", ["chutku", "backup", "restore", str(self.zip), "--include-security"]):
                cli.main()
        self.assertEqual((self.data / "telegram.json").read_text(), "{}")
        with patch("chutku.app.PROJECT_ROOT", self.base), patch("builtins.input", return_value="YES"), \
                patch("chutku.backup.backup_folder", return_value=self.folder), patch("builtins.print"):
            with patch("sys.argv", ["chutku", "backup", "restore", str(self.zip), "--include-security"]):
                cli.main()
        self.assertEqual((self.data / "telegram.json").read_text(), '{"chat_id": 666}')


if __name__ == "__main__":
    unittest.main()

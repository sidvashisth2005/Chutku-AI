"""X17 (2026-11-06): learn from a GitHub project without running any of it."""
import tempfile
import unittest
from pathlib import Path

from chutku import skill_import
from chutku.app import create_runtime

SKILL = "---\nname: karpathy-guidelines\ndescription: Think before coding.\n---\n# Rules\n1. Simplicity first.\n"


def fake_cloner(files):
    def cloner(url, target):
        for name, text in files.items():
            path = Path(target) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return "abc1234def"
    return cloner


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_skill_md_files_become_procedures_with_source_and_licence(self):
        out = skill_import.import_repo(self.base, "https://github.com/someone/guides", cloner=fake_cloner({
            "LICENSE": "MIT License\nCopyright", "skills/karpathy/SKILL.md": SKILL,
            "skills/bad/SKILL.md": "---\nname: ../escape\n---\nx"}))
        self.assertEqual((out["licence"], out["commit"], [p["name"] for p in out["procedures"]]),
                         ("MIT", "abc1234def", ["karpathy-guidelines"]))   # the unsafe name is skipped
        self.assertIn("Simplicity first", skill_import.read_procedure(self.base, "karpathy-guidelines"))
        self.assertIsNone(out["pending_skill"])

    def test_a_project_without_skill_md_goes_to_the_coder_and_stays_pending(self):
        asked = []
        out = skill_import.import_repo(self.base, "github.com/someone/tool.git", cloner=fake_cloner({
            "README.md": "Converts temperatures.", "LICENSE": "Apache License 2.0"}),
            creator=lambda base, request: (asked.append(request), {"name": "temp_convert", "pending": True})[1])
        self.assertEqual((out["licence"], out["pending_skill"]), ("Apache-2.0", "temp_convert"))
        self.assertIn("Converts temperatures.", asked[0])
        self.assertIn("do not import or download the project", asked[0])
        self.assertIn("skill approve temp_convert", out["skill_reply"])

    def test_only_github_project_links_are_accepted(self):
        for bad in ("https://evil.example/x/y", "github.com/x", "file:///C:/x", "https://github.com/a/..",
                    "https://github.com/x/y; rm -rf", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                skill_import.parse_repo(bad)
        with self.assertRaises(ValueError):
            skill_import.read_procedure(self.base, "../../secrets")

    def test_the_tools_ask_first_and_a_procedure_is_outside_text(self):
        with create_runtime(self.base / "state") as runtime:
            runtime.capability_grants.grant("process.launch")
            tool = runtime.registry.get("skill.import")
            self.assertTrue(tool.runs_code and tool.network_egress)   # always a click (D5)
            waiting = runtime.run("skill.import", {"repo": "https://github.com/a/b"}, provenance="delegated",
                                  autonomy="owner")
            self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        from chutku.agent_loop import TAINTING_TOOLS
        self.assertIn("skill.procedure", TAINTING_TOOLS)


if __name__ == "__main__":
    unittest.main()

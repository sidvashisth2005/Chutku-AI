"""docs/CODEMAP.md names every module, so an agent can find code without reading it all (2026-11-10)."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CodeMapTests(unittest.TestCase):
    def test_every_module_is_in_the_code_map(self):
        text = (ROOT / "docs" / "CODEMAP.md").read_text(encoding="utf-8")
        listed = set()
        folder = None
        for line in text.splitlines():
            if line.startswith("## `"):
                folder = line[4:].split("`")[0]
            elif line.startswith("- `") and folder:
                listed.add(folder + line[3:].split("`")[0])
        modules = {p.relative_to(ROOT).as_posix() for p in (ROOT / "chutku").rglob("*.py")}
        self.assertEqual(sorted(modules - listed), [], "regenerate docs/CODEMAP.md")
        self.assertEqual(sorted(listed - modules), [], "docs/CODEMAP.md names a module that no longer exists")


if __name__ == "__main__":
    unittest.main()

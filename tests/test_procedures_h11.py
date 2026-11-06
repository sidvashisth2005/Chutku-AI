"""H11: procedure skills (SKILL.md) with progressive disclosure: the planner sees only relevant names and
descriptions and reads a body with skill.procedure; a local SKILL.md can be added (text only)."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku import skill_import


SKILL = """---
name: rename-photos
description: Rename holiday photos by their date taken
---
1. Open the folder.
2. Sort by date taken.
"""


class ProcedureTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "inbox" / "SKILL.md"
        self.source.parent.mkdir()
        self.source.write_text(SKILL, encoding="utf-8")
        (self.source.parent / "run.ps1").write_text("Remove-Item C:\\ -Recurse", encoding="utf-8")

    def test_adding_a_local_skill_copies_only_the_text(self):
        added = skill_import.add_local(self.base, self.source)
        self.assertEqual(added, {"name": "rename-photos", "description": "Rename holiday photos by their date taken"})
        folder = skill_import.procedures_root(self.base) / "rename-photos"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["SKILL.md", "source.json"])   # no script copied
        self.assertIn("Sort by date taken", skill_import.read_procedure(self.base, "rename-photos"))

    def test_only_relevant_names_reach_the_planner(self):
        skill_import.add_local(self.base, self.source)
        shown = skill_import.relevant_procedures(self.base, "meri holiday photos ka naam date se rename karo")
        self.assertEqual(shown, [{"name": "rename-photos", "description": "Rename holiday photos by their date taken",
                                  "source": "added"}])
        self.assertNotIn("Sort by date", str(shown))                      # the body only through skill.procedure
        self.assertEqual(skill_import.relevant_procedures(self.base, "what time is it"), [])

    def test_hidden_characters_a_missing_name_or_a_duplicate_are_refused(self):
        hidden = self.base / "inbox" / "hidden.md"
        hidden.write_text(SKILL.replace("Open", "Op\u200ben"), encoding="utf-8")
        nameless = self.base / "inbox" / "nameless.md"
        nameless.write_text("just steps", encoding="utf-8")
        for bad in (hidden, nameless, self.base / "inbox" / "run.ps1", self.base / "missing.md"):
            with self.assertRaises(ValueError, msg=str(bad)):
                skill_import.add_local(self.base, bad)
        skill_import.add_local(self.base, self.source)
        with self.assertRaises(ValueError):
            skill_import.add_local(self.base, self.source)

    def test_the_session_context_lists_matching_procedures(self):
        from tests import test_dashboard as harness
        from tests.test_dashboard_agent import Scripted, proposal
        case = harness.DashboardTests("test_static_ui_has_no_embedded_session_secret_and_sets_security_headers")
        case.setUp()
        try:
            skill_import.add_local(case.base, self.source)
            case.server.planner_factory = lambda: (Scripted(proposal("done", reply="ok")), None)
            session = case.server.begin_session("holiday photos rename karo", "owner", "text")
            self.assertEqual([p["name"] for p in session.context["procedures"]["items"]], ["rename-photos"])
            import time
            deadline = time.monotonic() + 10
            while (session.status not in {"done", "clarify", "failed"} or case.server.action_lock.locked()
                   or case.server.parallel_running) and time.monotonic() < deadline:
                time.sleep(0.05)   # the worker also runs the after-task review before it lets go
        finally:
            case.tearDown()


if __name__ == "__main__":
    unittest.main()

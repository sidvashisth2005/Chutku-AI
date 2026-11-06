"""H10 lessons, H11 procedure drafts, H12 learning inbox, H13 curator, H27 "ye seekh lo", H28 journey (2026-11-07).
Nothing is saved without the owner's OK; the curator archives, never deletes."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from chutku import learning_inbox as li, recall, skill_import
from chutku.agent_loop import AgentSession


def session(goal, tools, *, status="done", planner="cloud:groq", tainted=False, lessons=None):
    s = AgentSession(goal, mode="owner", context={"lessons": {"items": lessons}} if lessons else {})
    s.steps = [{"tool": t, "arguments": {}, "state": "COMPLETED", "observation": "", "purpose": f"step {t}"}
               for t in tools]
    s.status, s.tainted = status, tainted
    s.planners = [{"planner": planner}]
    return s


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_a_fixed_mistake_becomes_a_lesson_only_after_the_owner_keeps_it(self):
        recall.log_conversation("spotify pe after party chalao", "Nahi hua.", status="failed",
                                tools=("screen.click",), base=self.base)
        made = li.after_session(self.base, session("spotify pe after party chalao",
                                                   ["app.spotify.play_playlist"]))
        self.assertEqual([m["kind"] for m in made], ["lesson"])
        self.assertEqual(li.relevant_lessons(self.base, "after party spotify pe chalao"), [])   # not kept yet
        li.keep(self.base, made[0]["id"])
        lessons = li.relevant_lessons(self.base, "after party spotify pe chalao")
        self.assertEqual((lessons[0]["use"], lessons[0]["avoid"]), (["app.spotify.play_playlist"], ["screen.click"]))
        self.assertEqual(li.items(self.base), [])
        li.after_session(self.base, session("after party chalao", [], status="failed", lessons=lessons))
        self.assertEqual(li.relevant_lessons(self.base, "after party spotify pe chalao"), [])   # demoted

    def test_untrusted_or_messaging_sessions_teach_nothing(self):
        recall.log_conversation("mammi ko hi bhejo", "Nahi hua.", status="failed", tools=("x.y",), base=self.base)
        self.assertEqual(li.after_session(self.base, session("mammi ko hi bhejo", ["message.send"])), [])
        self.assertEqual(li.after_session(self.base, session("a b c d", ["a.b", "c.d", "e.f"], tainted=True)), [])

    def test_a_verified_model_planned_task_offers_a_procedure(self):
        made = li.after_session(self.base, session("Downloads ki PDFs Study mein daalo",
                                                   ["files.find", "filesystem.move", "filesystem.list"]))
        self.assertEqual([m["kind"] for m in made], ["procedure"])
        self.assertEqual(li.after_session(self.base, session("quick one", ["a.b", "c.d", "e.f"], planner="quick")), [])
        li.keep(self.base)
        names = [p["name"] for p in skill_import.list_procedures(self.base)]
        self.assertEqual(names, ["downloads-ki-pdfs-study-mein-daalo"])

    def test_learning_from_a_document_drafts_a_procedure_into_the_inbox(self):
        doc = self.base / "how-to-rename-photos.md"
        doc.write_text("# Rename photos\n1. Open the folder\n2. Sort by date\n3. Rename with F2\n", encoding="utf-8")
        item = li.learn_from(self.base, path=doc)
        self.assertIn("3 steps", item["text"])
        self.assertIn("2. Sort by date", item["payload"]["text"])             # the doc's numbered list
        empty = self.base / "notes.txt"
        empty.write_text("no steps here", encoding="utf-8")
        for bad in (empty, self.base / "photo.jpg"):
            with self.assertRaises(ValueError):
                li.learn_from(self.base, path=bad)

    def test_the_curator_archives_old_things_and_keeps_the_owners(self):
        now = time.time()
        li._save(self.base, "lessons.json", [
            {"id": 1, "when": "a", "use": [], "avoid": [], "note": "old", "state": "active", "hits": 0,
             "created": now - 70 * 86400, "used": now - 70 * 86400},
            {"id": 2, "when": "b", "use": [], "avoid": [], "note": "stale", "state": "active", "hits": 0,
             "created": now - 40 * 86400, "used": now - 40 * 86400}])
        root = skill_import.procedures_root(self.base)
        for name, source in (("from-github", {"repo": "https://github.com/a/b", "last_read": now - 90 * 86400}),
                             ("mine", {"added_from": "D:/x.md"})):
            (root / name).mkdir(parents=True)
            (root / name / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n", encoding="utf-8")
            (root / name / "source.json").write_text(json.dumps(source), encoding="utf-8")
        report = li.curate(self.base, now=now)
        self.assertEqual((report["archived_lessons"], report["stale_lessons"], report["archived_procedures"]),
                         (1, 1, ["from-github"]))
        self.assertTrue((root / ".archive" / "from-github" / "SKILL.md").exists())   # moved, not deleted
        self.assertTrue((root / "mine").exists())

    def test_the_journey_counts_what_was_learned(self):
        li._save(self.base, "reflexes.json", [{"template": "x"}])
        li._save(self.base, "lessons.json", [{"id": 1, "when": "a", "use": [], "avoid": [], "note": "fix",
                                              "state": "active", "hits": 0, "created": time.time()}])
        out = li.journey(self.base)
        self.assertEqual((out["counts"]["lessons"], out["counts"]["instant_skills"]), (1, 1))
        self.assertIn("Ab tak seekha", out["summary"])


if __name__ == "__main__":
    unittest.main()

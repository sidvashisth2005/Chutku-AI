"""Asking for the Night Shift report (owner, 2026-10-07: "night report?" by voice got a made-up answer).

The report is read from data/nightshift/report-*.json by the nightshift.report tool, reached instantly by typed or
spoken Hinglish (also Devanagari), and the Live voice gets last night's line in its context so it never guesses.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind, nightshift
from chutku.app import create_runtime
from chutku.quick_intents import _say_night, quick_proposal
from chutku.voice.live import PERSONA, LiveConversation

REPORT = {"date": "2026-10-07", "started": "2026-10-07T04:09:01", "finished": "2026-10-07T04:23:07", "jobs": {
    "learned_skills": {"ok": True, "new_skills": 0},
    "reliability": {"ok": True, "keeps_failing": ["spotify.search on tool"]},
    "regression_replay": {"ok": True, "distinct_goals": 198,
                          "counts": {"same": 50, "changed": 4, "fails now": 1, "rejected plan": 7},
                          "rows": [{"goal": "Ita lag kar rahe.", "verdict": "fails now"},
                                   {"goal": "Calculator download.", "verdict": "changed"},
                                   {"goal": "open spotify", "verdict": "same"}]},
    "maintenance": {"ok": True},
    "fine_tune_readiness": {"ok": True, "verified_turns": 181, "needed": 300}}}

ASKS = ["Have you prepared the night report, bhai?", "night report", "night shift report", "raat ko kya kiya",
        "tumne raat ko kya kiya", "kal raat kya kiya", "nightshift ne kya kiya", "night shift ka report batao",
        "what did you do last night", "raat ki report", "नाइट शिफ्ट रिपोर्ट", "रात को क्या किया",
        "नाइट रिपोर्ट बताओ", "तुमने रात को क्या किया", "नाइट शिफ्ट ने क्या किया"]
NOT_ASKS = ["good night", "गुड नाइट", "night mode on", "raat ko 10 baje yaad dilana", "set night light on",
            "good night bolo mammi ko"]


class NightReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        nightshift.report_dir(self.base).mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def save(self, report):
        (nightshift.report_dir(self.base) / f"report-{report['date'].replace('-', '')}.json").write_text(
            json.dumps(report), encoding="utf-8")

    def test_summary_reports_the_saved_facts(self):
        self.save(REPORT)
        out = nightshift.report_summary(self.base)
        self.assertTrue(out["ran"])
        self.assertEqual((out["date"], out["requests_rechecked"], out["new_skills"]), ("2026-10-07", 198, 0))
        self.assertEqual(out["fails_now"], ["Ita lag kar rahe."])
        self.assertEqual(out["changed"], ["Calculator download."])
        self.assertEqual(out["fine_tune"], "181/300 verified turns")
        self.assertEqual(out["jobs_failed"], [])
        spoken = _say_night(out)
        for fact in ("2026-10-07", "04:09", "04:23", "198", "50 same", "4 changed", "1 now failing",
                     "Ita lag kar rahe", "spotify.search", "181/300"):
            self.assertIn(fact, spoken)

    def test_never_ran_and_failed_job_are_said_plainly(self):
        out = nightshift.report_summary(self.base)
        self.assertFalse(out["ran"])
        self.assertIn("not run yet", _say_night(out))
        broken = json.loads(json.dumps(REPORT))
        broken["jobs"]["maintenance"] = {"ok": False, "error": "disk"}
        self.save(broken)
        self.assertIn("maintenance", _say_night(nightshift.report_summary(self.base)))

    def test_every_way_of_asking_reaches_the_report_instantly(self):
        for goal in ASKS:
            proposal = quick_proposal(goal)
            self.assertIsNotNone(proposal, goal)
            self.assertEqual(proposal["next_steps"][0]["tool"], "nightshift.report", goal)

    def test_look_alikes_do_not(self):
        for goal in NOT_ASKS:
            proposal = quick_proposal(goal)
            tool = proposal["next_steps"][0]["tool"] if proposal and proposal.get("next_steps") else None
            self.assertNotEqual(tool, "nightshift.report", goal)

    def test_tool_is_registered_read_only_and_private(self):
        from chutku.agent_loop import PRIVATE_TOOLS
        with patch.object(mind, "PROJECT_ROOT", self.base), create_runtime(self.base / "state") as runtime:
            tool = runtime.registry.get("nightshift.report")
            self.assertEqual(int(tool.base_risk), 0)
            self.save(REPORT)
            result = tool.execute({}, None)
        self.assertEqual(result.output["requests_rechecked"], 198)
        self.assertIn("nightshift.report", PRIVATE_TOOLS)   # it lists the owner's own past requests


class FakeServer:
    def __init__(self, base):
        self.base = base

    def memory_slice(self, topic, budget):
        return {}


class LiveKnowsTheNightShiftTests(unittest.TestCase):
    def test_persona_names_the_feature_and_the_task(self):
        self.assertIn("Night Shift", PERSONA)
        self.assertIn("night report", PERSONA)
        self.assertIn("instead of saying no", PERSONA)

    def test_context_carries_last_nights_line(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            nightshift.report_dir(base).mkdir(parents=True)
            (nightshift.report_dir(base) / "report-20261007.json").write_text(json.dumps(REPORT), encoding="utf-8")
            live = LiveConversation(FakeServer(base), "key", audio=False)
            context = live._context()
        self.assertIn("Last Night Shift", context)
        self.assertIn("Raat ko (2026-10-07)", context)

    def test_context_without_a_report_says_nothing_about_it(self):
        with tempfile.TemporaryDirectory() as temp:
            live = LiveConversation(FakeServer(Path(temp)), "key", audio=False)
            self.assertNotIn("Night Shift", live._context())


if __name__ == "__main__":
    unittest.main()

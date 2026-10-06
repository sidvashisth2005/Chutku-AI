"""Night Shift (master plan S20): nightly jobs that improve Chutku without running anything."""
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku import nightshift
from chutku.app import create_runtime


def turn(said, tools, status="done", age=3600):
    return {"at": time.time() - age, "origin": "text", "said": said, "reply": "ok", "status": status,
            "tools": tools, "planners": ["local"]}


class FakeModel:
    name = "local"

    def __init__(self, plans):
        self.plans, self.asked = plans, []

    def propose(self, session, runtime, check=None):
        self.asked.append(session.goal)
        tools = self.plans[session.goal]
        status = "done" if tools is None else "continue" if tools else "clarify"   # None: answered without tools
        return {"status": status, "reply": "",
                "next_steps": [{"tool": t, "arguments": {}, "purpose": t} for t in tools or []]}, {}


class NightShiftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        (self.base / "data").mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def conversations(self, turns):
        (self.base / "data" / "conversations.jsonl").write_text(
            "".join(json.dumps(t) + "\n" for t in turns), encoding="utf-8")

    def test_replay_compares_plans_and_never_runs_anything(self):
        self.conversations([
            turn("what time is it", ["system.get_time"]),                        # rule: same
            turn("tell me whether Zzqx exists on this laptop", ["apps.installed"]),   # model now: same
            turn("summarise my week for me", ["files.recent"]),                   # model now: changed
            turn("do the impossible thing", ["web.search"]),                      # model now: no plan
            turn("which is bigger, 2^10 or 10^3", ["web.results"]),               # model now: answers directly
            turn("Summarise my week for me!", ["files.recent"], age=7200),        # same goal again: counted once
            turn("very old goal", ["system.get_time"], age=9 * 86400),            # older than 7 days: skipped
        ])
        model = FakeModel({"tell me whether Zzqx exists on this laptop": ["apps.installed"],
                           "summarise my week for me": ["log.recent"], "do the impossible thing": [],
                           "which is bigger, 2^10 or 10^3": None})
        with create_runtime(self.base) as runtime, \
                patch.object(runtime, "run", side_effect=AssertionError("Night Shift must not execute")):
            result = nightshift.regression_replay(self.base, runtime, model)
        verdicts = {row["goal"]: row["verdict"] for row in result["rows"]}
        self.assertEqual(result["distinct_goals"], 5)
        self.assertEqual(verdicts, {"what time is it": "same", "tell me whether Zzqx exists on this laptop": "same",
                                    "summarise my week for me": "changed", "do the impossible thing": "fails now",
                                    "which is bigger, 2^10 or 10^3": "answers directly"})
        self.assertNotIn("what time is it", model.asked)   # the rules answered it: no model round needed

    def test_without_the_model_unplanned_goals_are_marked_not_checked(self):
        self.conversations([turn("summarise my week for me", ["files.recent"])])
        with create_runtime(self.base) as runtime:
            result = nightshift.regression_replay(self.base, runtime, None)
        self.assertEqual(result["rows"][0]["verdict"], "not checked (needs the model)")

    def test_run_once_writes_a_report_with_every_job(self):
        self.conversations([turn("what time is it", ["system.get_time"])])
        (self.base / "data" / "heard.jsonl").write_text(
            json.dumps({"at": time.time() - 30 * 86400, "text": "old"}) + "\n"
            + json.dumps({"at": time.time(), "text": "new"}) + "\n", encoding="utf-8")
        with patch.object(nightshift, "on_ac_power", return_value=True):
            report = nightshift.run_once(self.base)
        self.assertEqual(set(report["jobs"]), {"learned_skills", "reliability", "regression_replay", "maintenance",
                                               "fine_tune_readiness"})
        self.assertTrue(all(job["ok"] for job in report["jobs"].values()), report["jobs"])
        self.assertEqual(report["jobs"]["maintenance"]["heard_lines_dropped"], 1)
        self.assertFalse(report["jobs"]["fine_tune_readiness"]["ready"])   # 1 verified turn, 300 needed
        self.assertTrue(Path(report["path"]).is_file())
        self.assertIn("Raat ko", nightshift.morning_line(self.base))
        self.assertIn("1 same", nightshift.morning_line(self.base))

    def test_on_battery_it_does_nothing(self):
        with patch.object(nightshift, "on_ac_power", return_value=False):
            report = nightshift.run_once(self.base)
        self.assertEqual((report.get("skipped"), report["jobs"]), ("on battery", {}))
        self.assertEqual(list(nightshift.report_dir(self.base).glob("report-*.json")), [])

    def test_one_failing_job_does_not_stop_the_others(self):
        with patch.object(nightshift, "on_ac_power", return_value=True), \
                patch.object(nightshift, "maintenance", side_effect=OSError("disk busy")):
            report = nightshift.run_once(self.base)
        self.assertFalse(report["jobs"]["maintenance"]["ok"])
        self.assertTrue(report["jobs"]["fine_tune_readiness"]["ok"])

    def test_it_waits_for_30_unused_minutes_after_4am(self):
        clock, waited = {"t": 0.0}, []

        def sleep(seconds):
            clock["t"] += seconds
            waited.append(seconds)
        # The owner uses the PC until 4:15, then sleeps: idle time counts up from then.
        idle = lambda: max(0.0, clock["t"] - 15 * 60)
        ready = nightshift.wait_for_idle(self.base, idle=idle, now=lambda: clock["t"], sleep=sleep,
                                         power=lambda: True, until=24 * 3600, poll=60)
        self.assertTrue(ready)
        self.assertEqual(clock["t"], 45 * 60)          # 4:45 = 4:15 + 30 unused minutes, not a fixed time

    def test_it_never_starts_on_battery_or_twice_a_day(self):
        clock = {"t": 0.0}
        tick = lambda s: clock.update(t=clock["t"] + s)
        self.assertFalse(nightshift.wait_for_idle(self.base, idle=lambda: 9999, now=lambda: clock["t"], sleep=tick,
                                                  power=lambda: False, until=3600, poll=60))
        with patch.object(nightshift, "on_ac_power", return_value=True):
            nightshift.run_once(self.base)
        clock["t"] = 0.0
        self.assertFalse(nightshift.wait_for_idle(self.base, idle=lambda: 9999, now=lambda: clock["t"], sleep=tick,
                                                  power=lambda: True, until=3600, poll=60))   # already ran today

    def test_fine_tune_readiness_needs_300_verified_turns(self):
        self.conversations([turn(f"goal {i}", ["system.get_time"], age=10) for i in range(300)])
        nightshift.report_dir(self.base).mkdir(parents=True)
        self.assertTrue(nightshift.lora_readiness(self.base)["ready"])
        self.assertTrue((nightshift.report_dir(self.base) / "lora-ready.json").is_file())


if __name__ == "__main__":
    unittest.main()

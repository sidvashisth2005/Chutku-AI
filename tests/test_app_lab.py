"""Action Lab (App Mastery A2). A fake runtime stands in for Runtime.run, so no test touches the screen."""
import json
from pathlib import Path
import tempfile
import unittest

from chutku.apps import atlas as atlas_module
from chutku.apps import lab

ATLAS = {
    "app": "demo", "name": "Demo", "window": {"exe": "Demo.exe"}, "uri_schemes": ["demo"],
    "actions": [
        {"id": "open", "title": "Open", "risk": "safe", "steps": [{"focus": True}], "check": {"window_open": True}},
        {"id": "shuffle", "title": "Shuffle", "risk": "safe", "steps": [{"keys": "ctrl+s"}], "lab": {"pair": True}},
        {"id": "repeat", "title": "Repeat", "risk": "safe", "steps": [{"keys": "ctrl+r"}], "lab": {"pair": 2}},
        {"id": "search", "title": "Search", "risk": "safe", "params": {"query": {"type": "text"}},
         "steps": [{"uri": "demo:search:{query}"}], "drill": {"query": "lofi"}},
        {"id": "play", "title": "Play", "risk": "safe", "params": {"name": {"type": "text"}},
         "steps": [{"focus": True}]},
        {"id": "like", "title": "Like", "risk": "changes", "steps": [{"keys": "alt+shift+b"}],
         "check": {"ocr_contains": "Liked"}},
        {"id": "send", "title": "Send", "risk": "consequential", "steps": [{"keys": "enter"}],
         "check": {"window_open": True}},
        {"id": "quit", "title": "Quit", "risk": "safe", "steps": [{"keys": "ctrl+q"}], "lab": {"skip": "stops the app"}},
    ]}


class FakeLedger:
    def __init__(self):
        self.rows = []

    def record(self, tool, target, **fields):
        self.rows.append((tool, fields))


class FakeRuntime:
    def __init__(self, failing=()):
        self.calls, self.failing, self.ledger = [], set(failing), FakeLedger()

    def run(self, tool, arguments):
        self.calls.append((tool, dict(arguments)))
        if tool in self.failing:
            return {"state": "COMPLETED", "output": {"ok": False, "error": "check failed: ocr_contains",
                                                     "seconds": 0.5}}
        return {"state": "COMPLETED", "output": {"ok": True, "seconds": 0.4}}


def paused_media():
    log = []

    def media(action):
        log.append(action)
        return {"status": "Playing"} if action == "status" and len(log) > 1 else {"status": "Paused"}
    return media, log


class LabTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.media, self.media_log = paused_media()

    def run_lab(self, runtime, **kwargs):
        return lab.run_lab(self.base, runtime, ATLAS, media=self.media, pause=0, **kwargs)

    def test_three_passes_verify_and_are_recorded(self):
        runtime = FakeRuntime()
        report = self.run_lab(runtime)
        self.assertEqual(report["verified"], ["open", "repeat", "search", "shuffle"])
        self.assertTrue(lab.verified(self.base, "demo", "open"))
        self.assertEqual(lab.verified_actions(self.base), {"demo": {"open", "repeat", "search", "shuffle"}})
        self.assertIn(("app.demo.search", {"query": "lofi"}), runtime.calls)
        self.assertEqual(len([r for r in runtime.ledger.rows if r[0] == "app.demo.open"]), 3)
        self.assertEqual(runtime.ledger.rows[0][1]["autonomy"], "lab")
        self.assertEqual(report["median_seconds"], 0.4)
        self.assertIn("4/8 actions verified", lab.describe(report))

    def test_toggles_are_pressed_back_to_where_they_started(self):
        runtime = FakeRuntime()
        self.run_lab(runtime, only={"shuffle", "repeat"})
        self.assertEqual(sum(1 for t, _ in runtime.calls if t == "app.demo.shuffle"), 6)   # 3 tries x 2
        self.assertEqual(sum(1 for t, _ in runtime.calls if t == "app.demo.repeat"), 9)    # 3 tries x 3

    def test_unsafe_skipped_and_missing_drill_skipped(self):
        runtime = FakeRuntime()
        report = self.run_lab(runtime)
        tools = {t for t, _ in runtime.calls}
        self.assertNotIn("app.demo.send", tools)       # consequential: never run by the lab
        self.assertNotIn("app.demo.like", tools)       # changes: only with include_changes
        self.assertNotIn("app.demo.quit", tools)       # lab.skip
        self.assertNotIn("app.demo.play", tools)       # needs a param, no drill value
        self.assertEqual(report["skipped"]["quit"], "stops the app")
        self.assertIn("no drill values", report["skipped"]["play"])
        report = self.run_lab(FakeRuntime(), only={"like", "send"}, include_changes=True)
        self.assertEqual(report["tried"], ["like"])

    def test_a_failure_stops_the_action_and_resets_its_streak(self):
        runtime = FakeRuntime()
        self.run_lab(runtime, only={"open"})
        self.assertTrue(lab.verified(self.base, "demo", "open"))
        broken = FakeRuntime(failing={"app.demo.open"})
        report = self.run_lab(broken, only={"open"})
        self.assertEqual(len(broken.calls), 1)          # not hammered after the first failure
        self.assertFalse(lab.verified(self.base, "demo", "open"))
        self.assertIn("ocr_contains", report["failed"]["open"])
        self.assertEqual(broken.ledger.rows[0][1]["verdict"], "FAIL")
        state = json.loads(lab.lab_path(self.base, "demo").read_text(encoding="utf-8"))
        self.assertEqual(state["actions"]["open"]["streak"], 0)

    def test_denied_step_is_a_failure(self):
        class Denying(FakeRuntime):
            def run(self, tool, arguments):
                self.calls.append((tool, arguments))
                return {"state": "DENIED", "reason": "policy"}
        report = self.run_lab(Denying(), only={"open"})
        self.assertEqual(report["failed"]["open"], "policy")
        self.assertEqual(report["verified"], [])

    def test_setup_action_runs_before_each_try(self):
        atlas = json.loads(json.dumps(ATLAS))
        atlas["actions"].append({"id": "previous", "title": "Previous", "risk": "safe", "steps": [{"media": "previous"}],
                                 "check": {"media_changed": True}, "lab": {"setup": "open"}})
        atlas_module.validate(atlas)
        runtime = FakeRuntime()
        lab.run_lab(self.base, runtime, atlas, only={"previous"}, media=self.media, pause=0)
        self.assertEqual([t for t, _ in runtime.calls], ["app.demo.open", "app.demo.previous"] * 3)
        atlas["actions"][-1]["lab"] = {"setup": "send"}     # setup may only be a safe action
        with self.assertRaises(atlas_module.AtlasError):
            atlas_module.validate(atlas)

    def test_music_paused_before_is_paused_again(self):
        self.run_lab(FakeRuntime(), only={"open"})
        self.assertEqual(self.media_log[-1], "pause")

    def test_corrupt_lab_file_counts_as_nothing_verified(self):
        path = lab.lab_path(self.base, "demo")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertFalse(lab.verified(self.base, "demo", "open"))
        self.assertEqual(lab.verified_actions(self.base), {})

    def test_validator_checks_drill_and_lab_fields(self):
        atlas_module.validate(json.loads(json.dumps(ATLAS)))
        bad = json.loads(json.dumps(ATLAS))
        bad["actions"][3]["drill"] = {"other": "x"}
        with self.assertRaises(atlas_module.AtlasError):
            atlas_module.validate(bad)
        bad = json.loads(json.dumps(ATLAS))
        bad["actions"][1]["lab"] = {"pair": 9}
        with self.assertRaises(atlas_module.AtlasError):
            atlas_module.validate(bad)

    def test_shipped_spotify_atlas_is_valid_and_has_lab_fields(self):
        atlases, errors = atlas_module.load_all()
        self.assertEqual(errors, {})
        spotify = {a["id"]: a for a in atlases["spotify"]["actions"]}
        self.assertEqual(spotify["play_playlist"]["drill"], {"name": "After Party"})
        self.assertIn("skip", spotify["quit"]["lab"])
        self.assertEqual(spotify["go_playlists"]["steps"][1]["keys"], "alt+shift+0")


if __name__ == "__main__":
    unittest.main()

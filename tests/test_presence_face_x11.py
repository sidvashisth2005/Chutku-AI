"""X11 + X12 (2026-11-05): the presence orb's face: its mood from the state, and amplitude lip-sync."""
import json
import re
import shutil
import subprocess
import unittest

from chutku.dashboard import DashboardServer, PROJECT_ROOT
from tests import test_dashboard as _harness

SCRIPT = PROJECT_ROOT / "chutku" / "web" / "presence.js"


class MoodTests(unittest.TestCase):
    def test_each_phase_has_its_mood(self):
        expected = {"idle": "calm", "listening": "listening", "confirm": "listening", "clarify": "confused",
                    "thinking": "thinking", "running": "thinking", "speaking": "speaking", "error": "sorry",
                    "paused": "sleepy", "done": "calm"}
        for phase, mood in expected.items():
            self.assertEqual(DashboardServer.presence_mood(phase, []), mood, phase)

    def test_happy_only_after_a_verified_done(self):
        ok = {"state": "COMPLETED", "verified": True}
        self.assertEqual(DashboardServer.presence_mood("done", [ok, ok]), "happy")
        self.assertEqual(DashboardServer.presence_mood("done", [ok, {"state": "COMPLETED", "verified": False}]), "calm")
        self.assertEqual(DashboardServer.presence_mood("done", [ok, {"state": "FAILED", "verified": False}]), "calm")
        self.assertEqual(DashboardServer.presence_mood("running", [ok]), "thinking")


class MoodPayloadTests(unittest.TestCase):
    setUp, tearDown, request = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown, \
        _harness.DashboardTests.request

    def test_presence_payload_carries_the_mood(self):
        _, body, _ = self.request("/api/presence")
        self.assertEqual((body["phase"], body["mood"]), ("idle", "calm"))
        from chutku.core.action_control import ActionControl
        ActionControl(self.base).pause()
        _, body, _ = self.request("/api/presence")
        self.assertEqual((body["phase"], body["mood"]), ("paused", "sleepy"))


class FaceScriptTests(unittest.TestCase):
    def test_the_face_is_drawn_on_the_orb_without_files_or_cdn(self):
        script = SCRIPT.read_text(encoding="utf-8")
        for needle in ("function drawFace(", "function mouthShape(", "prefers-reduced-motion", "drawFace(t, c,",
                       "state.mood", "Amplitude lip-sync"):
            self.assertIn(needle, script)
        self.assertEqual(script.count("requestAnimationFrame("), 2)   # still one loop: the first frame and draw's own
        self.assertNotRegex(script, r"https?://|new Image|\.png|\.svg")

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_mouth_shapes_follow_the_voice_level_without_flicker(self):
        subprocess.run(["node", "--check", str(SCRIPT)], check=True, capture_output=True, timeout=30)
        source = re.search(r"function mouthShape\(level, previous\)\{.*?\r?\n\}", SCRIPT.read_text(encoding="utf-8"),
                           re.S).group(0)
        cases = [[0, 0], [0.1, 0], [0.3, 0], [0.5, 0], [0.9, 0],   # closed, slight, round, open, wide
                 [0.21, 1], [0.19, 2], [0.07, 0], [0.04, 1],      # within 0.03 of an edge the shape holds
                 [0.16, 2], [0.09, 0]]                            # further away it changes
        out = subprocess.run(["node", "-e", source + f";console.log(JSON.stringify({json.dumps(cases)}"
                              ".map(([l, p]) => mouthShape(l, p))))"],
                             check=True, capture_output=True, text=True, timeout=30).stdout
        self.assertEqual(json.loads(out), [0, 1, 2, 3, 4, 1, 2, 0, 1, 1, 1])


if __name__ == "__main__":
    unittest.main()

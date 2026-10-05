import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from chutku import vision
from chutku.app import create_runtime
from chutku.tools import screen_vision
from chutku.voice.handsfree import split_wake


def shot(value=0):
    return vision.Shot(np.full((100, 200, 3), value, np.uint8), 0, 0, 200, 100, {"title": "App", "executable": "a.exe"})


class VisionCoreTests(unittest.TestCase):
    def test_boxes_map_to_screen_pixels_and_png_is_valid(self):
        s = vision.Shot(np.zeros((1080, 1920, 3), np.uint8), 100, 50, 1920, 1080)
        self.assertEqual(vision.to_pixels(s, [500, 250, 600, 500]), (100 + 480, 50 + 540, 100 + 960, 50 + 648))
        with self.assertRaises(ValueError):
            vision.to_pixels(s, [600, 250, 500, 500])
        png = vision.encode_png(vision.scaled(s.pixels))
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(vision.scaled(s.pixels).shape[1], vision.MAX_WIDTH)

    def test_see_parses_gemini_and_drops_bad_boxes(self):
        answer = ('{"summary":"Notepad","answer":"a file","elements":[{"label":"File","kind":"menu",'
                  '"box_2d":[0,0,100,100]},{"label":"broken","kind":"x","box_2d":[5,5,1,1]}]}')
        seen = vision.see(shot(), "what?", "k" * 30, generate=lambda *a, **k: (answer, "gemini-lite"))
        self.assertEqual([e["id"] for e in seen["elements"]], ["e1"])
        self.assertEqual(seen["elements"][0]["rect"], (0, 0, 20, 10))

    def test_change_detection(self):
        self.assertFalse(vision.changed(shot(0), shot(0)))
        self.assertTrue(vision.changed(shot(0), shot(200)))


class ScreenToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        for capability in ("screen.observe", "desktop.input"):
            self.runtime.capability_grants.grant(capability)
        self.clicks = []
        patches = [patch.object(vision, "capture", side_effect=[shot(0), shot(255)] * 10),
                   patch.object(vision, "click_at", side_effect=lambda *a, **k: self.clicks.append(a)),
                   patch.object(vision, "crop_text", return_value="")]
        self.patches = patches
        for p in patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.runtime.close()
        self.temp.cleanup()

    def remember(self, label):
        vision.remember_seen(shot(), [{"id": "e1", "label": label, "kind": "button", "rect": (10, 10, 30, 20)}])

    def test_understand_needs_local_vision_or_gemini(self):
        with patch("chutku.tools.builder.gemini_allowed", return_value=None), \
                patch("chutku.local_vision.available", return_value=False):
            result = self.runtime.run("screen.understand", {"question": "what is this"})
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("cloud.gemini", result["output"]["error"])

    def test_understand_uses_local_vision_without_any_cloud_grant(self):
        seen = {"summary": "Notepad", "answer": "", "elements": [], "model": "local:Qwen3-VL-4B"}
        with patch("chutku.local_vision.available", return_value=True), \
                patch.object(vision, "see", return_value=seen) as see, \
                patch("chutku.gemini.generate_best", side_effect=AssertionError("Gemini must not be called")):
            result = self.runtime.run("screen.understand", {"question": "what is this"})
        self.assertEqual(str(result["state"]), "COMPLETED", result)
        self.assertIsNone(see.call_args.args[2])     # no Gemini key passed: this runtime has no cloud grant

    def test_plain_click_runs_and_is_verified_by_a_visible_change(self):
        self.remember("Next")
        result = self.runtime.run("screen.click", {"element": "e1"})
        self.assertEqual(str(result["state"]), "COMPLETED", result)
        self.assertEqual(self.clicks, [(20, 15, "left")])

    def test_consequential_click_is_refused_even_if_only_local_ocr_sees_it(self):
        self.remember("Send")
        self.assertEqual(str(self.runtime.run("screen.click", {"element": "e1"})["state"]), "FAILED")
        self.remember("Continue")  # Gemini's label looks harmless, but the pixels say "Place order"
        with patch.object(vision, "crop_text", return_value="Place order"):
            refused = self.runtime.run("screen.click", {"element": "e1"})
        self.assertEqual(str(refused["state"]), "FAILED")
        self.assertIn("click_risky", refused["output"]["error"])
        self.assertEqual(self.clicks, [])

    def test_risky_click_always_waits_for_the_user_even_in_auto_edits(self):
        self.remember("Send")
        waiting = self.runtime.run("screen.click_risky", {"element": "e1"}, provenance="delegated",
                                   autonomy="auto_edits")
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        self.assertEqual(self.clicks, [])

    def test_only_fresh_element_ids_can_be_clicked(self):
        with vision._lock:
            vision._state["seen"] = None
        self.assertEqual(str(self.runtime.run("screen.click", {"element": "e1"})["state"]), "FAILED")
        self.remember("Next")
        self.assertEqual(str(self.runtime.run("screen.click", {"element": "e9"})["state"]), "FAILED")
        with vision._lock:
            vision._state["seen"]["at"] = time.monotonic() - vision.ELEMENT_SECONDS - 1
        self.assertEqual(str(self.runtime.run("screen.click", {"element": "e1"})["state"]), "FAILED")
        self.assertEqual(self.clicks, [])


class WakePhraseTests(unittest.TestCase):
    def test_both_wake_phrases(self):
        self.assertEqual(split_wake("Chutku sun, spotify kholo"), (True, "spotify kholo"))
        self.assertEqual(split_wake("Chutku soon."), (True, ""))
        self.assertEqual(split_wake("Oye Chutku kitne baje hain"), (True, "kitne baje hain"))
        self.assertEqual(split_wake("Chutku, sunday ko yaad dilana"), (True, "sunday ko yaad dilana"))
        for text in ("the sun is hot", "Chotu sun", "sun lo"):
            self.assertEqual(split_wake(text), (False, ""), text)


if __name__ == "__main__":
    unittest.main()

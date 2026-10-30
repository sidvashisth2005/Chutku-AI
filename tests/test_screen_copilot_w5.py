"""W5 (2026-10-29): the screen copilot. One fast answer about what the owner is looking at, the window cropped,
private apps never uploaded, a hard time budget, local vision offline, and Ctrl+Alt+S."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import numpy as np

from chutku.quick_intents import quick_proposal
from chutku.tools import screen_vision
from chutku.vision import Shot


def shot(rect=(100, 50, 500, 350), executable="Code.exe"):
    pixels = np.zeros((600, 800, 3), np.uint8)
    pixels[50:350, 100:500] = 200
    return Shot(pixels, 0, 0, 800, 600, {"title": "main.py - VS Code", "executable": executable, "rect": rect})


class CropTests(unittest.TestCase):
    def test_only_the_foreground_window_is_sent(self):
        part = screen_vision.window_pixels(shot())
        self.assertEqual(part.shape, (300, 400, 3))
        self.assertTrue((part == 200).all())

    def test_whole_screen_when_asked_or_the_window_is_unknown(self):
        self.assertEqual(screen_vision.window_pixels(shot(), "screen").shape, (600, 800, 3))
        self.assertEqual(screen_vision.window_pixels(shot(rect=None)).shape, (600, 800, 3))
        self.assertEqual(screen_vision.window_pixels(shot(rect=(0, 0, 10, 10))).shape, (600, 800, 3))   # too small


class AskTests(unittest.TestCase):
    def test_cloud_answers_first(self):
        answer, model = screen_vision.ask_screen(shot(), "ye error kya hai?", "key",
                                                 cloud=lambda: ("Import error: install numpy.", "gemini-lite"),
                                                 local=lambda: ("local", "qwen-vl"))
        self.assertEqual((answer, model), ("Import error: install numpy.", "gemini-lite"))

    def test_a_slow_cloud_is_cut_off_and_the_local_model_answers(self):
        def slow():
            time.sleep(2)
            return "late", "gemini"
        started = time.monotonic()
        answer, model = screen_vision.ask_screen(shot(), "q", "key", cloud=slow, local=lambda: ("local answer", "qwen-vl"),
                                                 budget=0.3)
        self.assertEqual(model, "qwen-vl")
        self.assertLess(time.monotonic() - started, 1.5)

    def test_offline_without_a_key_uses_local(self):
        answer, model = screen_vision.ask_screen(shot(), "q", None, local=lambda: ("seen locally", "qwen-vl"))
        self.assertEqual(answer, "seen locally")

    def test_nothing_available_is_an_honest_failure(self):
        def broken():
            raise RuntimeError("503")
        with patch("chutku.local_vision.available", return_value=False):
            with self.assertRaises(OSError) as caught:
                screen_vision.ask_screen(shot(), "q", "key", cloud=broken)
        self.assertIn("cloud: RuntimeError", str(caught.exception))

    def test_a_private_app_is_never_looked_at(self):
        with patch.object(screen_vision.vision, "moment", return_value=shot(executable="mybank.exe")), \
                patch.object(screen_vision, "_private_apps", return_value={"mybank.exe"}), \
                patch.object(screen_vision, "ask_screen", side_effect=AssertionError("must not upload")):
            result = screen_vision._ask({"when": "hotkey_moment"}, _Context())
        self.assertEqual(result.verification, screen_vision.Verification.FAIL)
        self.assertIn("private", result.output["error"])

    def test_arguments_are_checked(self):
        for bad in ({"question": "x" * 301}, {"scope": "everything"}, {"when": "yesterday"}, {"other": 1}):
            with self.assertRaises(ValueError):
                screen_vision._validate_ask(bad)
        screen_vision._validate_ask({"question": "ye kya hai", "scope": "screen", "when": "now"})


class _Context:
    def granted(self, _capability):
        return False


class PhraseTests(unittest.TestCase):
    def test_owner_phrases_reach_the_copilot(self):
        for said in ("ye kya hai", "is error ko fix karo", "screen dekh ke batao ye error kya hai", "explain this error",
                     "is page ka summary do", "summarise this page", "what am I looking at"):
            proposal = quick_proposal(said)
            self.assertEqual(proposal["next_steps"][0]["tool"], "screen.ask", said)
            self.assertEqual(proposal["next_steps"][0]["arguments"]["when"], "hotkey_moment")

    def test_ordinary_requests_do_not(self):
        for said in ("open notepad", "this page is slow", "error log file kholo"):
            proposal = quick_proposal(said)
            tools = [s["tool"] for s in proposal["next_steps"]] if proposal else []
            self.assertNotIn("screen.ask", tools, said)


class HotkeyTests(unittest.TestCase):
    def test_ctrl_alt_s_keeps_the_moment_and_asks_the_copilot(self):
        from chutku.dashboard import DashboardServer
        with TemporaryDirectory() as temp:
            server = DashboardServer(Path(temp), port=0)
            try:
                goals = []
                server._listen_once = lambda wait_seconds=None: "ye button kya karta hai"
                server.begin_session = lambda goal, mode, origin, **k: goals.append((goal, origin)) or \
                    type("S", (), {"id": "s1"})()
                with patch("chutku.vision.remember_moment") as kept, patch("chutku.voice.handsfree.chime"):
                    server.screen_copilot()
                kept.assert_called_once()
                self.assertEqual(goals, [("screen dekh ke batao: ye button kya karta hai", "voice")])
                self.assertEqual(quick_proposal(goals[0][0])["next_steps"][0]["tool"], "screen.ask")
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()

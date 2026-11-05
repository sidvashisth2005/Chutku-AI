"""F2/F4 (2026-10-29): room talk is counted, not stored; misheard noise is read back instead of run."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from chutku.core.action_control import ActionControl
from chutku.core.preferences import Preferences
from chutku.dashboard import DashboardServer
from chutku.voice import heard
from chutku.voice.plausible import plausible


class AmbientLogTests(unittest.TestCase):
    def test_ignored_speech_is_counted_without_words(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            heard.count_ignored("wake", base)
            heard.count_ignored("wake", base)
            day = time.strftime("%Y-%m-%d")
            self.assertEqual(heard.ignored_counts(base)[day]["wake"], 2)
            self.assertFalse(heard.heard_path(base).exists())

    def test_debug_window(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            self.assertFalse(heard.ambient_logging(base))
            Preferences(base).update({"heard_ambient_until": time.time() + 3600})
            self.assertTrue(heard.ambient_logging(base))
            Preferences(base).update({"heard_ambient_until": time.time() - 1})
            self.assertFalse(heard.ambient_logging(base))

    def test_wake_listener_stores_wakes_but_only_counts_room_talk(self):
        from chutku.voice.handsfree import WakeListener
        with TemporaryDirectory() as temp:
            base = Path(temp)
            woke = []
            texts = iter(["So I called you, you can call me anytime.", "Oye Chutku, Spotify kholo"])
            listener = WakeListener(lambda command: woke.append(command),
                                    lambda segment: {"text": next(texts), "confidence": 0.8}, base=base)
            worker = threading.Thread(target=listener._transcriber, daemon=True)
            worker.start()
            listener._segments.put((b"\0" * 3200, 0.1))
            listener._segments.put((b"\0" * 3200, 0.1))
            deadline = time.monotonic() + 5
            while not woke and time.monotonic() < deadline:
                time.sleep(0.02)
            listener.stop_event.set()
            worker.join(2)
            self.assertEqual(woke, ["Spotify kholo"])
            rows = [json.loads(line) for line in heard.heard_path(base).read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["decision"] for r in rows], ["wake"])        # the room talk's words are not stored
            self.assertEqual(heard.ignored_counts(base)[time.strftime("%Y-%m-%d")]["wake"], 1)


class PlausibleTests(unittest.TestCase):
    def test_owners_misheard_tries_are_not_requests(self):
        for said in ("Watch out brother.", "Basic presentation.", "Higaton speech", "Arela Upadi Om."):
            self.assertFalse(plausible(said), said)

    def test_real_requests_and_questions_pass(self):
        for said in ("Spotify kholo", "After Party chalao", "kitne baje hain", "what time is it", "next song",
                     "YouTube", "volume 30", "Good evening.", "मम्मी को गुड नाइट भेजो", "is it raining?"):
            self.assertTrue(plausible(said), said)
        self.assertTrue(plausible("AK ko hi", known_names=["AK"]))


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.server = DashboardServer(self.base, port=0)
        self.spoken = []
        self.server._speak = self.spoken.append
        self.server._say = self.spoken.append
        self.server.voice_replies = True

    def tearDown(self):
        if self.server.action_lock.acquire(timeout=10):   # let a background agent worker finish first
            self.server.action_lock.release()
        time.sleep(0.2)
        self.server.server_close()
        self.temp.cleanup()

    def wait_spoken(self):
        deadline = time.monotonic() + 3
        while not self.spoken and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_misheard_voice_is_read_back_not_run(self):
        session = self.server.begin_session("Watch out brother.", "owner", "voice")
        snapshot = session.snapshot()
        self.assertEqual(snapshot["status"], "clarify")
        self.assertIn("Watch out brother", snapshot["reply"])
        self.assertEqual(snapshot["steps"], [])
        self.wait_spoken()
        self.assertIn("Maine suna", self.spoken[0])

    def test_typed_text_is_never_gated(self):
        planned = []

        class Planner:
            name = "test"

            def propose(self, session, runtime, check=None):
                planned.append(session.goal)
                return {"status": "done", "reply": "ok", "declared_plan": [], "next_steps": []}, {
                    "planner": "test", "seconds": 0, "backend": "test"}
        self.server.planner_factory = lambda: (Planner(), None)
        session = self.server.begin_session("Basic presentation.", "owner", "text")
        deadline = time.monotonic() + 5
        while session.snapshot()["status"] not in {"done", "failed", "clarify"} and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertNotIn("Maine suna", session.snapshot().get("reply") or "")

    def test_paused_voice_resume_refusal_is_spoken(self):
        ActionControl(self.base).pause()
        self.server.begin_session("resume", "owner", "voice")
        self.wait_spoken()
        self.assertIn("Ctrl+Alt+Space", self.spoken[0])


if __name__ == "__main__":
    unittest.main()


class SwitchToolTests(unittest.TestCase):
    def test_each_switch_writes_its_preference(self):
        from unittest.mock import patch
        from chutku import mind
        from chutku.tools.mind_tools import _switch
        with TemporaryDirectory() as temp, patch.object(mind, "PROJECT_ROOT", Path(temp)):
            prefs = Preferences(Path(temp))
            for setting, key, on_value, off_value in (("conversation", "conversation", True, False),
                                                      ("hindi_listening", "stt_language", "en|hi", "en"),
                                                      ("cloud_brain", "brain", "cloud_first", "local")):
                self.assertEqual(_switch({"setting": setting, "on": True}, None).output["now"], on_value)
                self.assertEqual(prefs.load()[key], on_value)
                self.assertEqual(_switch({"setting": setting, "on": False}, None).output["now"], off_value)
            _switch({"setting": "heard_debug", "on": True}, None)
            self.assertTrue(heard.ambient_logging(Path(temp)))
            _switch({"setting": "heard_debug", "on": False}, None)
            self.assertFalse(heard.ambient_logging(Path(temp)))

    def test_phrases(self):
        from chutku.quick_intents import quick_proposal
        cases = {"conversation mode on": ("conversation", True), "live mode off": ("conversation", False),
                 "hindi bhi samjho": ("hindi_listening", True), "sirf english suno": ("hindi_listening", False),
                 "cloud brain off": ("cloud_brain", False), "heard debug on": ("heard_debug", True)}
        for said, (setting, on) in cases.items():
            step = quick_proposal(said)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("settings.chutku", {"setting": setting, "on": on}))
        self.assertEqual(quick_proposal("local mode")["next_steps"][0]["tool"], "settings.offline_mode")


class SyntheticOriginTests(unittest.TestCase):
    from tests import test_dashboard as _harness
    setUp, tearDown, request = _harness.DashboardTests.setUp, _harness.DashboardTests.tearDown, \
        _harness.DashboardTests.request

    def test_a_script_request_is_logged_as_script(self):
        status, body, _ = self.request("/api/chat", {"message": "what time is it", "mode": "auto_safe"},
                                       headers={"X-Chutku-Synthetic": "1"})
        self.assertEqual(status, 200, body)
        rows = [json.loads(line) for line in (self.base / "data" / "conversations.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["origin"], "script")
        status, body, _ = self.request("/api/chat", {"message": "what time is it", "mode": "auto_safe"})
        rows = [json.loads(line) for line in (self.base / "data" / "conversations.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["origin"], "text")

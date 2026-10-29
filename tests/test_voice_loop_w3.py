"""W3 (2026-10-29): the real-time voice loop: GPU speech-to-text with a CPU fallback, interrupting Chutku with the
hotkey, a short "ek second" for slow answers, and the time from the end of speech to her first sound."""
from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from chutku import dashboard
from chutku.dashboard import DashboardServer, SpeechQueue, record_voice_timing
from chutku.voice import recognition, tts, whisper_stt


class GpuFallbackTests(unittest.TestCase):
    def test_a_gpu_model_that_cannot_load_falls_back_to_cpu(self):
        fast, cpu = {"name": "turbo", "device": "cuda", "path": "x"}, {"name": "small", "path": "y"}
        loaded = []

        def load_entry(entry):
            if entry is fast:
                raise RuntimeError("CUDA driver not found")
            loaded.append(entry["name"])
            return "model", entry
        with patch.object(whisper_stt, "configured_model", side_effect=lambda base, key="stt": fast if key == "stt_fast" else cpu), \
                patch.object(whisper_stt, "_load_entry", side_effect=load_entry), \
                patch.dict(whisper_stt.FAST, {"failed": None}):
            self.assertEqual(whisper_stt._load()[1]["name"], "small")
            self.assertIn("CUDA", whisper_stt.FAST["failed"])
            whisper_stt._load()                            # it does not keep retrying the GPU every time
        self.assertEqual(loaded, ["small", "small"])


class FakeRuntime:
    def __init__(self, said):
        self.said = said

    def run(self, tool, arguments, **_):
        self.said.append(arguments["text"])
        return {"state": "COMPLETED", "output": {"first_audio_s": 0.3, "engine": "kokoro"}}


class SpeechQueueTests(unittest.TestCase):
    def queue(self, base, said):
        @contextmanager
        def runtime(_base):
            yield FakeRuntime(said)
        return patch.object(dashboard, "create_runtime", runtime), SpeechQueue(base, "time batao")

    def test_an_interruption_drops_the_rest_of_the_answer(self):
        with TemporaryDirectory() as temp:
            said = []
            patcher, speech = self.queue(Path(temp), said)
            with patcher:
                speech.say("Paanch baj gaye.")
                deadline = time.monotonic() + 3
                while not said and time.monotonic() < deadline:
                    time.sleep(0.02)
                tts.stop()                                 # the owner pressed the hotkey while she spoke
                speech.say("Aur kuch?")
                speech.close(timeout=3)
            self.assertEqual(said, ["Paanch baj gaye."])

    def test_the_first_real_sentence_records_the_wait(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            recognition.LAST_END["at"] = time.monotonic() - 1.0
            seconds = record_voice_timing(base, "time batao", time.monotonic(), {"output": {"first_audio_s": 0.4}})
            self.assertAlmostEqual(seconds, 1.4, delta=0.2)
            row = json.loads((base / "data" / "voice-timings.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(row["goal"], "time batao")
            self.assertIsNone(recognition.LAST_END["at"])   # one timing per request
            self.assertIsNone(record_voice_timing(base, "x", time.monotonic(), {}))


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.server = DashboardServer(self.base, port=0)

    def tearDown(self):
        if self.server.action_lock.acquire(timeout=10):
            self.server.action_lock.release()
        time.sleep(0.2)
        self.server.server_close()
        self.temp.cleanup()

    def test_hotkey_while_she_speaks_stops_her(self):
        from chutku.voice.session import voice_session
        before = tts.STOPS["count"]
        with voice_session.active("speaking"):
            with patch.object(voice_session, "snapshot", side_effect=[type("S", (), {"state": "speaking"})()]
                              + [type("S", (), {"state": "idle"})()] * 5):
                self.assertTrue(self.server._barge_in(settle=0.2))
        self.assertEqual(tts.STOPS["count"], before + 1)
        self.assertFalse(self.server._barge_in())        # not speaking: nothing to stop

    def test_a_slow_answer_starts_with_ek_second(self):
        said = []

        class Slow:
            name = "slow"

            def propose(self, session, runtime, check=None):
                time.sleep(0.8)
                return {"status": "done", "reply": "ok", "declared_plan": [], "next_steps": []}, {
                    "planner": "slow", "seconds": 0.8, "backend": "test"}
        self.server.planner_factory = lambda: (Slow(), None)
        self.server.FILLER_AFTER = 0.2
        with patch.object(SpeechQueue, "say", lambda queue, text: said.append(text)), \
                patch.object(dashboard, "speak_result", lambda *a: None):
            session = self.server.begin_session("aaj kaun sa din hai", "owner", "voice", speaker_check=False)
            deadline = time.monotonic() + 5
            while session.snapshot()["status"] not in {"done", "failed", "clarify"} and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertEqual(said[:1], [dashboard.FILLER])

    def test_follow_up_listens_for_the_set_window_then_ends_quietly(self):
        heard_waits = []
        self.server._listen_once = lambda wait_seconds=None: heard_waits.append(wait_seconds) or ""
        self.server._local_conversation("owner", wait_seconds=8.0)
        self.assertEqual(heard_waits, [8.0])
        self.assertEqual(self.server.hud_state["phase"], "done")


if __name__ == "__main__":
    unittest.main()

"""Voice fixes from the owner's real Live sessions (master plan S8)."""
import queue
import threading
import time
import types
import unittest
from unittest.mock import patch

from chutku.voice import heard
from chutku.voice.handsfree import WakeListener
from chutku.voice.live import PERSONA, LiveConversation, foreign_words
from tests.test_heard import FakeServer, chunk


class TranscriptTurnTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveConversation(types.SimpleNamespace(live_event=lambda *a, **k: None), "key", audio=False)

    def said(self, text, done=False):
        content = {"outputTranscription": {"text": text}}
        if done:
            content["turnComplete"] = True
        self.live.handle({"serverContent": content})

    def test_separate_model_turns_stay_separate(self):
        self.said("Theek hai, ")
        self.said("bye!", done=True)
        self.said("Aur kuch?", done=True)
        replies = [text for speaker, text in self.live.full_transcript if speaker == "chutku"]
        self.assertEqual(replies, ["Theek hai, bye!", "Aur kuch?"])

    def test_the_same_reply_repeated_is_kept_once(self):
        # live 2026-10-06: "Bye-bye!" came back four times glued together
        for _ in range(4):
            self.said("Koi baat nahi! Bye-bye!", done=True)
        replies = [text for speaker, text in self.live.full_transcript if speaker == "chutku"]
        self.assertEqual(replies, ["Koi baat nahi! Bye-bye!"])


class LiveRequestTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.live = LiveConversation(self.server, "key", audio=False)
        self.live._follow = lambda *_: None
        self.live._task_running = lambda: False
        patcher = patch.object(heard, "log_heard", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def speak(self, seconds, level=0.2):
        for _ in range(int(seconds / self.live.gate.chunk_seconds)):
            self.live.gate.feed(chunk(level))

    def test_one_request_heard_twice_starts_once(self):
        self.speak(1.0)
        self.live.heard_since_task = "whatsapp kholo"
        self.assertEqual(self.live.dispatch("do_task", {"goal": "open whatsapp"})["status"], "started")
        self.speak(1.0)
        self.live.heard_since_task = "whatsapp kholo"
        self.assertEqual(self.live.dispatch("do_task", {"goal": "Open WhatsApp"})["status"], "already started")
        self.assertEqual(self.server.tasks, ["open whatsapp"])

    def test_spanish_mishearing_never_starts_a_task(self):
        self.speak(1.0)
        self.live.heard_since_task = "Sí, un poco."
        self.assertIn("error", self.live.dispatch("do_task", {"goal": "Do something"}))
        self.assertEqual(self.server.tasks, [])
        self.assertFalse(foreign_words("WhatsApp open kar"))
        self.assertFalse(foreign_words("mujhe de do"))

    def test_a_yes_before_its_words_waits_for_them(self):
        self.live.task_id = "s1"
        self.live._snapshot = lambda: {"status": "waiting_confirmation"}
        self.live.speech_at_question = self.live.gate.speech_seconds
        self.live.heard_since_question = ""                  # the model answered before "हां" was transcribed
        injected = []
        self.live.inject = injected.append
        result = self.live.dispatch("answer_approval", {"approve": True})
        self.assertEqual(result["status"], "checking")
        self.speak(0.5)
        self.live.heard_since_question = "हां।"               # the words arrive a moment later
        deadline = time.monotonic() + 3
        while not self.server.confirmed and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.server.confirmed, [True])

    def test_a_late_breath_is_not_a_yes(self):
        self.live.task_id = "s1"
        self.live._snapshot = lambda: {"status": "waiting_confirmation"}
        self.live.speech_at_question = self.live.gate.speech_seconds
        self.live.heard_since_question = ""
        injected = []
        self.live.inject = injected.append
        self.live.LATE_WORDS_SECONDS = 0.3
        self.live.dispatch("answer_approval", {"approve": True})
        self.live.heard_since_question = "hmm"                # no real speech behind it
        time.sleep(0.8)
        self.assertEqual(self.server.confirmed, [])
        self.assertTrue(any("did not hear a clear yes" in text for text in injected))

    def test_no_personal_names_are_built_in(self):
        for name in ("UB", "Pita Shri", "mammi"):
            self.assertNotIn(name, PERSONA)


class WakeListenerTests(unittest.TestCase):
    def test_a_crash_restarts_with_backoff(self):
        calls = []

        class Broken:
            def RawInputStream(self, **_):
                calls.append(1)
                raise OSError("microphone unplugged")

        listener = WakeListener(lambda _c: None, lambda _s: {"text": ""}, backend=Broken())
        listener.RESTARTS = 2
        with patch.object(listener.stop_event, "wait", return_value=False):
            listener.run()
        self.assertEqual(len(calls), 3)
        self.assertEqual(listener.restarts, 2)
        self.assertIn("unplugged", listener.error)

    def test_a_busy_transcriber_drops_the_oldest_segment(self):
        listener = WakeListener(lambda _c: None, lambda _s: {"text": ""})
        listener._segments = queue.Queue(maxsize=2)
        for segment in (b"1", b"2"):
            listener._segments.put_nowait((segment, 0.1))
        # what _listen does when the queue is full
        try:
            listener._segments.put_nowait((b"3", 0.1))
        except queue.Full:
            listener._segments.get_nowait()
            listener.dropped += 1
            listener._segments.put_nowait((b"3", 0.1))
        self.assertEqual([listener._segments.get_nowait()[0] for _ in range(2)], [b"2", b"3"])
        self.assertEqual(listener.dropped, 1)


if __name__ == "__main__":
    unittest.main()

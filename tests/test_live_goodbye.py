"""Ending a live conversation (owner 2026-10-11): "bye" must not cut Chutku off mid-sentence. She finishes the
reply she is speaking, a soft beep plays, then it closes."""
import asyncio
import base64
import types
import unittest
from unittest.mock import patch

from chutku.voice.live import LiveConversation


def conversation(audio=True):
    events = []
    server = types.SimpleNamespace(live_event=lambda name, **_: events.append(name))
    live = LiveConversation(server, "key", audio=audio)
    live.active.set()
    return live, events


def audio_message(n=3200):
    return {"serverContent": {"modelTurn": {"parts": [{"inlineData": {"data": base64.b64encode(b"\x01" * n).decode()}}]}}}


class GoodbyeTests(unittest.TestCase):
    def test_end_conversation_does_not_close_at_once(self):
        live, events = conversation()
        reply = live.dispatch("end_conversation", {})
        self.assertEqual(reply["status"], "ending")
        self.assertTrue(live.active.is_set())       # still open: the goodbye is still to be spoken
        self.assertNotIn("ended", events)

    def test_waits_while_speaking_then_closes_when_turn_is_done(self):
        live, _ = conversation()
        live.dispatch("end_conversation", {})
        live.handle(audio_message())                 # "Theek hai, bye!" arrives
        self.assertFalse(live._goodbye_done())       # still in the speaker buffer: not cut off
        live._playback.clear()                       # the speaker has played it
        self.assertFalse(live._goodbye_done())       # the model's turn is not finished yet
        live.handle({"serverContent": {"turnComplete": True}})
        self.assertTrue(live._goodbye_done())

    def test_an_earlier_finished_turn_does_not_count(self):
        live, _ = conversation()
        live.handle({"serverContent": {"turnComplete": True}})   # an earlier reply ended before "bye"
        live.dispatch("end_conversation", {})
        self.assertFalse(live._goodbye_done())

    def test_no_goodbye_audio_still_ends_soon(self):
        live, _ = conversation()
        live.dispatch("end_conversation", {})
        live.ending_at -= live.GOODBYE_SILENT_SECONDS + 0.1
        self.assertTrue(live._goodbye_done())

    def test_never_waits_forever(self):
        live, _ = conversation()
        live.dispatch("end_conversation", {})
        live._playback.extend(b"\x01" * 10)          # something stuck in the buffer
        live.ending_at -= live.GOODBYE_MAX_SECONDS
        self.assertTrue(live._goodbye_done())

    def test_watch_beeps_then_reports_ended(self):
        live, events = conversation()
        live.dispatch("end_conversation", {})
        live.handle({"serverContent": {"turnComplete": True}})
        beeps = []
        with patch("chutku.voice.handsfree.chime", lambda kind="listen": beeps.append(kind)):
            asyncio.run(asyncio.wait_for(live._watch(), 5))
        self.assertEqual(beeps, ["done"])
        self.assertEqual(events[-1], "ended")


if __name__ == "__main__":
    unittest.main()

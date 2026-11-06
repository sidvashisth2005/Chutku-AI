"""Mic mute (owner, 2026-10-05): friends' laughs must not stop Chutku's answer; Ctrl+Alt+M / HUD button."""
import asyncio
import base64
import contextlib
import json
import time
import types
import unittest
from array import array
from unittest.mock import patch

from chutku.voice import mic
from chutku.voice import recognition, speaker   # noqa: F401  loaded before sys.modules is patched (numpy loads once)


def loud(samples=640):
    return array("h", [8000 if i % 2 else -8000 for i in range(samples)]).tobytes()


class MicSwitchTests(unittest.TestCase):
    def tearDown(self):
        mic.set_muted(False)

    def test_toggle(self):
        self.assertFalse(mic.muted())
        self.assertTrue(mic.toggle())
        self.assertFalse(mic.toggle())


class LiveWhileMutedTests(unittest.TestCase):
    def tearDown(self):
        mic.set_muted(False)

    def run_mic(self, chunks, muted):
        from chutku.voice.live import LiveConversation
        sent = []

        class WS:
            async def send(self, text):
                sent.append(json.loads(text))
                if len(sent) >= len(chunks):
                    live.active.clear()

        live = LiveConversation(types.SimpleNamespace(live_event=lambda *a, **k: None), "key", audio=False)
        live.ws = WS()
        live.active.set()

        class Stream:
            def __init__(self, callback=None, **_):
                self.callback = callback

            def __enter__(self):
                for chunk in chunks:
                    self.callback(chunk, len(chunk) // 2, None, None)
                return self

            def __exit__(self, *_):
                return False
        fake_sd = types.SimpleNamespace(RawInputStream=Stream)
        mic.set_muted(muted)
        with patch.dict("sys.modules", {"sounddevice": fake_sd}), \
                patch.object(LiveConversation, "_speaker", lambda self: contextlib.nullcontext()):
            async def hear_and_send():
                with contextlib.ExitStack() as stack:
                    await asyncio.wait_for(live._microphone(live._hear(stack)), 5)
            asyncio.run(hear_and_send())
        return [base64.b64decode(m["realtimeInput"]["audio"]["data"]) for m in sent]

    def test_speech_during_the_connection_is_kept_and_sent_once_connected(self):
        """Z4: the microphone opens before the ~1.3 s connection, so the first words are not lost."""
        from chutku.voice.live import LiveConversation
        events, sent = [], []
        server = types.SimpleNamespace(live_event=lambda *a, **k: None)
        live = LiveConversation(server, "key", audio=True)

        class WS:
            async def send(self, text):
                sent.append(json.loads(text))
                if len(sent) >= 5:
                    live.active.clear()

        async def slow_open(self):
            events.append(("open", "heard" in events))
            await asyncio.sleep(0.2)   # the connection
            self.model = "m"
            return WS()

        async def idle(self):
            while self.active.is_set():
                await asyncio.sleep(0.02)

        class Stream:
            def __init__(self, callback=None, **_):
                self.callback = callback

            def __enter__(self):
                events.append("heard")
                for _ in range(5):
                    self.callback(loud(), 640, None, None)   # the owner already speaks while it connects
                return self

            def __exit__(self, *_):
                return False
        live.active.set()
        with patch.dict("sys.modules", {"sounddevice": types.SimpleNamespace(RawInputStream=Stream)}), \
                patch.object(LiveConversation, "_speaker", lambda self: contextlib.nullcontext()), \
                patch.object(LiveConversation, "_open", slow_open), \
                patch.object(LiveConversation, "_receive", idle), patch.object(LiveConversation, "_watch", idle):
            asyncio.run(asyncio.wait_for(live._main(), 5))
        self.assertEqual(events, ["heard", ("open", True)])   # listening began before connecting
        self.assertEqual(len(sent), 5)                         # every chunk said meanwhile reached the session
        self.assertTrue(any(set(base64.b64decode(m["realtimeInput"]["audio"]["data"])) != {0} for m in sent))

    def test_muted_mic_sends_only_silence(self):
        audio = self.run_mic([loud()] * 5, muted=True)
        self.assertEqual(len(audio), 5)
        self.assertTrue(all(set(piece) == {0} for piece in audio))     # nothing from the room reaches Google

    def test_unmuted_loud_speech_passes(self):
        audio = self.run_mic([loud()] * 5, muted=False)
        self.assertTrue(any(set(piece) != {0} for piece in audio))

    def test_muted_pause_does_not_end_the_conversation(self):
        from chutku.voice import live as live_module
        conversation = live_module.LiveConversation(types.SimpleNamespace(live_event=lambda *a, **k: None), "key",
                                                    audio=False)
        conversation.active.set()
        conversation.last_activity = time.monotonic() - 999
        conversation._task_running = lambda: False
        mic.set_muted(True)

        async def check():
            watcher = asyncio.create_task(conversation._watch())
            await asyncio.sleep(1.2)
            alive = not watcher.done()
            conversation.active.clear()
            await asyncio.wait_for(watcher, 2)
            return alive
        self.assertTrue(asyncio.run(check()))


class ServerMuteTests(unittest.TestCase):
    def tearDown(self):
        mic.set_muted(False)

    def test_toggle_mute_updates_the_hud_and_conversation_end_unmutes(self):
        from chutku.dashboard import DashboardServer
        server = types.SimpleNamespace(hud_state={}, _hud_show=lambda: None, wake=None,
                                       hotkey=types.SimpleNamespace(mute_hotkey="Ctrl+Alt+Shift+Space"))
        with patch("chutku.voice.handsfree.chime"):
            self.assertTrue(DashboardServer.toggle_mute(server))
        self.assertIn("muted", server.hud_state["message"].lower())
        self.assertIn("Ctrl+Alt+Shift+Space", server.hud_state["message"])     # the key that really works
        live = types.SimpleNamespace(closed=types.SimpleNamespace(wait=lambda: None), full_transcript=[], error=None)
        server.live = None
        server.base = "."
        with patch("chutku.recall.log_voice"):
            DashboardServer._after_live(server, live)
        self.assertFalse(mic.muted())


if __name__ == "__main__":
    unittest.main()

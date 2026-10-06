import tempfile
import threading
import time
import types
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from chutku.core.preferences import Preferences
from chutku.voice import handsfree
from chutku.voice.handsfree import Segmenter, WakeListener, split_wake
from chutku.voice.session import voice_session


def chunk(level):
    return array("h", [int(level * 32767)] * 1600).tobytes()


class WakePhraseTests(unittest.TestCase):
    def test_accepts_common_transcriptions(self):
        for text, command in [("Oye Chutku, open Spotify.", "open Spotify"), ("Owe Chutku, Gaana roko.", "Gaana roko"),
                              ("Oichutku, open Spotify.", "open Spotify"), ("Owei chudku.", ""),
                              ("Chutku, what time is it?", "what time is it"), ("Hey Chutku", ""),
                              ("Oye chutkoom.", ""), ("Oe chuku, open Spotify.", "open Spotify"),
                              ("Oye Chhutku, open Spotify.", "open Spotify"), ("Chhutku what time is it", "what time is it"),
                              ("oye chhutkoo gaana roko", "gaana roko"), ("ओए छुटकू, टाइम बताओ", "taaim bataao"),
                              ("Oye chhuku", "")]:
            self.assertEqual(split_wake(text), (True, command), text)

    def test_rejects_near_misses_and_ordinary_speech(self):
        for text in ("Oye Chotu, idhar aao.", "Ek chutki bhar namak daal do.", "Chutney bana do please.",
                     "Hey Google, what's the weather?", "Open the window, it is hot.", "The chutney was great",
                     "Please ask Chutku later", "", "Kuch toh gadbad hai.", "Chuku open Spotify",
                     "Oye chuki idhar aa", "Oye chikoo khaoge?",
                     "Oye Chhotu idhar aao", "chhutki bhar namak", "छोटू इधर आओ"):
            self.assertEqual(split_wake(text), (False, ""), text)


class SegmenterTests(unittest.TestCase):
    def test_emits_one_segment_per_utterance_with_preroll(self):
        segmenter = Segmenter(threshold=0.012)
        out = [segmenter.feed(chunk(level)) for level in [0.0] * 5 + [0.2] * 10 + [0.0] * 8]
        segments = [s for s in out if s]
        self.assertEqual(len(segments), 1)
        self.assertGreaterEqual(len(segments[0]) // 3200, 10)

    def test_short_clicks_are_ignored(self):
        segmenter = Segmenter(threshold=0.012)
        out = [segmenter.feed(chunk(level)) for level in [0.2, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0] * 3]
        self.assertEqual([s for s in out if s], [])


class AdaptiveThresholdTests(unittest.TestCase):
    def test_quiet_room_lowers_threshold_so_soft_speech_is_segmented(self):
        segmenter = Segmenter()
        out = [segmenter.feed(chunk(level)) for level in [0.001] * 40 + [0.015] * 10 + [0.001] * 8]
        self.assertAlmostEqual(segmenter.threshold, 0.008)       # the floor: a keyboard or fan no longer counts
        self.assertEqual(len([s for s in out if s]), 1)

    def test_sound_just_above_old_floor_is_not_speech(self):
        segmenter = Segmenter()
        out = [segmenter.feed(chunk(level)) for level in [0.001] * 40 + [0.006] * 10 + [0.001] * 8]
        self.assertEqual([s for s in out if s], [])

    def test_two_loud_chunks_are_a_click_not_a_start(self):
        segmenter = Segmenter(threshold=0.012)
        out = [segmenter.feed(chunk(level)) for level in ([0.0] * 5 + [0.2, 0.2] + [0.0] * 10) * 3]
        self.assertEqual([s for s in out if s], [])

    def test_noise_step_up_lifts_the_floor_instead_of_endless_segments(self):
        segmenter = Segmenter()
        out = [segmenter.feed(chunk(level)) for level in [0.001] * 40 + [0.02] * 300]   # a fan switches on
        self.assertLessEqual(len([s for s in out if s]), 1)
        self.assertGreater(segmenter.threshold, 0.02)

    def test_noisy_room_raises_threshold(self):
        segmenter = Segmenter()
        for _ in range(200):
            segmenter.feed(chunk(0.003))
        self.assertGreater(segmenter.threshold, 0.012)


class FakeStream:
    def __init__(self, levels, done):
        self.levels, self.done = list(levels), done

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _frames):
        if not self.levels:
            self.done.set()
            time.sleep(0.01)
            return chunk(0.0), False
        return chunk(self.levels.pop(0)), False


class WakeListenerTests(unittest.TestCase):
    def listen(self, transcripts, speaking=False):
        done, woke, heard = threading.Event(), [], list(transcripts)
        utterance = [0.0] * 3 + [0.2] * 8 + [0.0] * 8
        backend = types.SimpleNamespace(RawInputStream=lambda **_: FakeStream(utterance * len(transcripts), done))
        listener = WakeListener(lambda command: woke.append(command),
                                lambda pcm: {"text": heard.pop(0) if heard else ""}, backend=backend)
        context = voice_session.active("speaking") if speaking else _Null()
        with context:
            listener.start()
            done.wait(5)
            time.sleep(0.2)
        listener.stop()
        listener.join(2)
        return woke, listener

    def test_only_wake_phrase_triggers(self):
        with patch.object(voice_session, "quiet_for", return_value=5.0):
            woke, listener = self.listen(["Hello there, dinner is ready.", "Oye Chutku, open Spotify."])
        self.assertEqual(woke, ["open Spotify"])
        self.assertEqual(listener.segments_heard, 2)
        self.assertIsNone(listener.error)

    def test_deaf_while_the_mic_is_muted(self):
        from chutku.voice import mic
        mic.set_muted(True)
        try:
            with patch.object(voice_session, "quiet_for", return_value=5.0):
                woke, listener = self.listen(["Oye Chutku, open Spotify."])
        finally:
            mic.set_muted(False)
        self.assertEqual((woke, listener.segments_heard), ([], 0))

    def test_deaf_while_chutku_speaks(self):
        woke, listener = self.listen(["Oye Chutku, open Spotify."], speaking=True)
        self.assertEqual(woke, [])
        self.assertEqual(listener.segments_heard, 0)


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class PreferencesTests(unittest.TestCase):
    def test_defaults_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            prefs = Preferences(Path(temp))
            self.assertEqual(prefs.load(), {"handsfree_mode": "owner", "wake_word": False, "conversation": True, "browser": "brave",
                                        "heard_log": True, "offline_mode": False, "earned_autonomy_relax": False})
            for bad in ({"handsfree_mode": "yolo"}, {"wake_word": "yes"}, {"conversation": 1}, {"other": 1}, {}):
                with self.assertRaises(ValueError):
                    prefs.update(bad)
            prefs.update({"wake_word": True, "handsfree_mode": "review", "conversation": False, "browser": "edge", "heard_log": True,
                                                              "offline_mode": False, "earned_autonomy_relax": False})
            self.assertEqual(Preferences(Path(temp)).load(), {"handsfree_mode": "review", "wake_word": True,
                                                              "conversation": False, "browser": "edge", "heard_log": True,
                                                              "offline_mode": False, "earned_autonomy_relax": False})
            with self.assertRaises(ValueError):
                prefs.update({"browser": "netscape"})


class HandsfreeServerTests(unittest.TestCase):
    from tests import test_dashboard as _harness
    setUp, request = _harness.DashboardTests.setUp, _harness.DashboardTests.request

    def tearDown(self):
        if self.server.action_lock.acquire(timeout=10):
            self.server.action_lock.release()
        self._harness.DashboardTests.tearDown(self)

    def test_preferences_endpoint_and_latest_session(self):
        status, body, _ = self.request("/api/preferences", {"handsfree_mode": "review"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["handsfree"]["handsfree_mode"], "review")
        self.assertEqual(self.request("/api/preferences", {"handsfree_mode": "everything"})[0], 400)
        status, body, _ = self.request("/api/agent/latest")
        self.assertEqual((status, body["id"]), (200, None))

    def test_spoken_command_after_wake_runs_with_handsfree_mode(self):
        from tests.test_dashboard_agent import Scripted, proposal
        planner = Scripted(proposal(steps=[("system.get_time", {})]), proposal("done", reply="noon"))
        self.server.planner_factory = lambda: (planner, None)
        self.server.preferences.update({"handsfree_mode": "auto_safe"})
        with patch("chutku.dashboard.speak_result"), patch.object(handsfree, "chime"):
            self.server.handsfree_request("what time is it")
        session = self.server.agent_sessions.get(self.server.latest_session_id).snapshot()
        self.assertEqual((session["origin"], session["mode"], session["status"]), ("voice", "auto_safe", "done"))

    def test_busy_server_queues_a_spoken_order_and_runs_it_after(self):
        from tests.test_dashboard_agent import Scripted, proposal
        planner = Scripted(proposal(steps=[("system.get_time", {})]), proposal("done", reply="noon"))
        self.server.planner_factory = lambda: (planner, None)
        self.server.action_lock.acquire()                        # another order is running
        with patch.object(handsfree, "chime") as chime, patch("chutku.dashboard.speak_result"):
            self.server.handsfree_request("what time is it")       # returns at once: never blocks the listener
            chime.assert_called_with("listen")
            session = self.server.agent_sessions.get(self.server.latest_session_id)
            self.assertEqual(session.status, "queued")
            self.server.action_lock.release()                    # the running order ends
            self.server._next_work()
            for _ in range(100):
                if session.status == "done":
                    break
                time.sleep(0.05)
        self.assertEqual(session.status, "done")

    def test_orders_queue_in_order_skip_stopped_ones_and_announce_once(self):
        from chutku import dashboard
        from tests.test_dashboard_agent import Scripted, proposal
        ran, announced = [], []
        self.server.planner_factory = lambda: (Scripted(proposal(steps=[("system.get_time", {})]),
                                                        proposal("done", reply="ok")), None)
        self.server.action_lock.acquire()
        with patch("chutku.dashboard.speak_result"),                 patch.object(self.server, "_announce_batch", side_effect=lambda batch: announced.append(
                    [item.goal for item in batch])):
            sessions = [self.server.begin_session(goal, "auto_safe", "text") for goal in ("first", "second", "third")]
            self.assertEqual([item.status for item in sessions], ["queued"] * 3)
            self.assertEqual(self.server.queued_ids(), [item.id for item in sessions])
            sessions[1].status = "cancelled"                       # stopped while waiting
            original = self.server._run_work
            self.server._run_work = lambda session, action: (ran.append(session.goal), original(session, action))
            self.server.action_lock.release()
            self.server._next_work()
            for _ in range(200):
                if all(item.status in {"done", "cancelled"} for item in sessions) and not self.server.action_lock.locked():
                    break
                time.sleep(0.05)
            time.sleep(0.2)
        self.assertEqual(ran, ["first", "third"])
        self.assertEqual([item.status for item in sessions], ["done", "cancelled", "done"])
        self.assertEqual(announced, [["first", "third"]])
        self.server.action_lock.acquire()
        try:
            for index in range(dashboard.MAX_QUEUED):
                self.server.begin_session(f"wait {index}", "auto_safe", "text")
            with self.assertRaises(dashboard.ExecutionBusy):
                self.server.begin_session("one too many", "auto_safe", "text")
        finally:
            with self.server.queue_lock:
                self.server.work_queue.clear()
            self.server.action_lock.release()

    def test_stop_while_busy_stops_running_and_queued_work_at_once(self):
        from tests.test_dashboard_agent import Scripted, proposal
        self.server.planner_factory = lambda: (Scripted(proposal(steps=[("system.get_time", {})]),
                                                        proposal("done", reply="ok")), None)
        self.server.action_lock.acquire()                               # an order is running
        try:
            waiting = [self.server.begin_session(goal, "auto_safe", "text") for goal in ("first", "second")]
            with patch.object(self.server, "stop_session") as stop_running:
                stop = self.server.begin_session("ruko", "auto_safe", "voice")
            self.assertEqual(stop.status, "done")                       # handled at once, never queued
            self.assertIn("Stopped (2 tasks)", stop.reply)
            self.assertEqual([item.status for item in waiting], ["cancelled", "cancelled"])
            self.assertEqual(self.server.queued_ids(), [])
            stop_running.assert_not_called()                            # (the held lock is not a real session)
        finally:
            self.server.action_lock.release()

    def test_pause_by_voice_pauses_actions(self):
        from chutku.core.action_control import ActionControl
        session = self.server.begin_session("pause actions", "auto_safe", "voice")
        try:
            self.assertEqual(session.status, "done")
            self.assertTrue(ActionControl(self.server.base).paused)
        finally:
            ActionControl(self.server.base).resume()

    def test_help_in_chat_is_the_friendly_answer_not_a_tool_dump(self):
        status, body, _ = self.request("/api/chat", {"message": "what can you do", "mode": "auto_safe"})
        self.assertEqual(status, 200, body)
        self.assertNotEqual(body.get("kind"), "direct")      # was a raw dump of every tool definition
        session = self.server.agent_sessions.get(body["session"]["id"])
        for _ in range(100):
            if session.status == "done":
                break
            time.sleep(0.05)
        self.assertIn("undo that", session.reply)

    def test_hotkey_listening_still_waits_while_busy(self):
        self.server.action_lock.acquire()
        try:
            with patch.object(handsfree, "chime") as chime:
                self.server.handsfree_request()                    # the microphone is not taken mid-action
            chime.assert_called_with("busy")
            self.assertIsNone(self.server.latest_session_id)
        finally:
            self.server.action_lock.release()


if __name__ == "__main__":
    unittest.main()

"""Only real speech counts (owner report 2026-10-04: "Chutku hears random noises that aren't there")."""
import math
import tempfile
import types
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

from chutku.voice import heard, whisper_stt
from chutku.voice.heard import NoiseGate, log_heard, meaningful, recent_heard
from chutku.voice.live import LiveConversation


def chunk(level, samples=640):
    value = int(level * 32768 * math.sqrt(2))
    return array("h", [value if i % 2 else -value for i in range(samples)]).tobytes()


class FilterTests(unittest.TestCase):
    def test_noise_inventions_are_not_speech(self):
        for text in ("Thank you.", "Thanks for watching!", "[Music]", "(noise)", "♪ ♪", "you", "Bye.", "hi",
                     "Subtitles by the Amara.org community", "you you you you", "hmm", "", "  ", "a"):
            self.assertFalse(meaningful(text), text)

    def test_real_short_commands_pass(self):
        for text in ("agla gaana", "ruko", "haan", "हाँ", "volume badhao", "brightness 50 karo",
                     "mammi ko bolo main aa raha hu"):
            self.assertTrue(meaningful(text), text)

    def test_lone_yes_no_only_in_an_answer_moment(self):
        for text in ("yes", "ok", "hmm", "no"):
            self.assertFalse(meaningful(text), text)
            self.assertTrue(meaningful(text, short_answers_ok=True), text)
        self.assertFalse(meaningful("Thank you.", short_answers_ok=True))


class GateTests(unittest.TestCase):
    def test_quiet_room_noise_is_sent_as_nothing(self):
        gate = NoiseGate(0.04)
        out = [gate.feed(chunk(0.004)) for _ in range(100)]
        self.assertTrue(all(o == [] for o in out))
        self.assertEqual(gate.speech_seconds, 0.0)

    def test_speech_passes_with_preroll_and_hangover(self):
        gate = NoiseGate(0.04)
        for _ in range(50):
            gate.feed(chunk(0.002))
        first = gate.feed(chunk(0.1))
        self.assertGreater(len(first), 1)                       # pre-roll keeps the start of the word
        self.assertEqual(gate.feed(chunk(0.002)), [chunk(0.002)])   # hangover keeps the end
        self.assertGreater(gate.speech_seconds, 0)

    def test_fan_switching_on_does_not_hold_the_gate_open(self):
        gate = NoiseGate(0.04)
        out = [gate.feed(chunk(0.03)) for _ in range(300)]       # 12 s of steady fan noise
        self.assertEqual(out[-50:], [[]] * 50)

    def test_own_voice_needs_much_louder_speech_to_interrupt(self):
        gate = NoiseGate(0.04)
        for _ in range(50):
            gate.feed(chunk(0.002))
        self.assertEqual(gate.feed(chunk(0.02), speaking=True), [])   # echo of Chutku's voice
        self.assertTrue(gate.feed(chunk(0.2), speaking=True))         # the owner talking over it


class LogTests(unittest.TestCase):
    def test_log_and_read_back_and_toggle(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_heard("wake", "Thank you.", "ignored", confidence=0.31, base=tmp)
            log_heard("live", "agla gaana", "task: next song", base=tmp)
            rows = recent_heard(base=tmp)
            self.assertEqual([r["text"] for r in rows], ["agla gaana", "Thank you."])
            from chutku.core.preferences import Preferences
            Preferences(Path(tmp)).update({"heard_log": False})
            log_heard("wake", "something", "ignored", base=tmp)
            self.assertEqual(len(recent_heard(base=tmp)), 2)


class FakeServer:
    def __init__(self):
        self.tasks, self.confirmed = [], []

    def live_task(self, goal):
        self.tasks.append(goal)
        return types.SimpleNamespace(id="s1")

    def confirm_session(self, task_id, approve):
        self.confirmed.append(approve)

    def live_event(self, *_):
        pass


class LiveGuardTests(unittest.TestCase):
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

    def test_noise_turned_into_words_does_not_start_a_task(self):
        self.speak(2.0, level=0.003)                                # only room noise reached the gate
        self.live.heard_since_task = "brightness 50 karo"           # ...but Google transcribed something
        result = self.live.dispatch("do_task", {"goal": "Set brightness to 50"})
        self.assertIn("Did you say", result["error"])
        self.assertEqual(self.server.tasks, [])

    def test_invented_text_does_not_start_a_task(self):
        self.speak(1.0)
        self.live.heard_since_task = " Thank you."
        self.assertIn("error", self.live.dispatch("do_task", {"goal": "Say thanks"}))
        self.assertEqual(self.server.tasks, [])

    def test_clear_request_starts_and_the_next_needs_new_speech(self):
        self.speak(1.0)
        self.live.heard_since_task = "agla gaana chalao"
        self.assertEqual(self.live.dispatch("do_task", {"goal": "Next song"})["status"], "started")
        self.live.heard_since_task = "agla gaana chalao"           # no new speech since
        self.assertIn("error", self.live.dispatch("do_task", {"goal": "Next song"}))
        self.assertEqual(self.server.tasks, ["Next song"])

    def test_wake_opening_is_trusted(self):
        self.live.trust_opening("youtube kholo")
        started = self.live.dispatch("do_task", {"goal": "Open YouTube"})
        self.assertEqual(started["status"], "started")
        self.assertIn("NOT finished", started["note"])   # the model must wait for the real result (2026-10-05)

    def test_noise_hmm_does_not_approve_but_spoken_haan_does(self):
        self.live.task_id = "s1"
        self.live._snapshot = lambda task_id=None: {"id": "s1", "status": "waiting_confirmation"}
        self.live.speech_at_question = self.live.gate.speech_seconds
        self.live.heard_since_question = " hmm"                     # no loud audio behind it
        self.assertIn("error", self.live.dispatch("answer_approval", {"approve": True}))
        self.speak(0.5)
        self.live.heard_since_question = " haan"
        self.assertEqual(self.live.dispatch("answer_approval", {"approve": True})["status"], "approved")
        self.assertEqual(self.server.confirmed, [True])

    def test_filtered_text_does_not_keep_the_conversation_open(self):
        self.live.last_activity = 0.0
        self.live.handle({"serverContent": {"inputTranscription": {"text": "Thank you."}}})
        self.assertEqual(self.live.last_activity, 0.0)
        self.live.handle({"serverContent": {"inputTranscription": {"text": "agla gaana"}}})
        self.assertGreater(self.live.last_activity, 0.0)


class WhisperSettingsTests(unittest.TestCase):
    def run_whisper(self, segments):
        calls = {}

        def transcribe(*_args, **kwargs):
            calls.update(kwargs)
            return iter(segments), types.SimpleNamespace(language="hi", language_probability=0.9)
        model = types.SimpleNamespace(transcribe=transcribe)
        with patch.object(whisper_stt, "_load", return_value=(model, {"name": "test"})):
            return whisper_stt.transcribe_pcm(chunk(0.2) * 10), calls

    def test_vad_and_no_random_retries(self):
        _, calls = self.run_whisper([])
        self.assertTrue(calls["vad_filter"])
        self.assertEqual(calls["temperature"], 0.0)

    def test_noisy_segment_dropped_real_one_kept(self):
        seg = lambda text, lp, ns: types.SimpleNamespace(text=text, avg_logprob=lp, no_speech_prob=ns)
        result, _ = self.run_whisper([seg(" agla gaana", -0.2, 0.1), seg(" subscribe karo", -1.2, 0.8)])
        self.assertEqual(result["text"], "agla gaana")

    def test_prompt_echo_is_dropped(self):
        seg = types.SimpleNamespace(text=" Spotify kholo. Open Notepad. Next song.", avg_logprob=-0.3, no_speech_prob=0.2)
        result, _ = self.run_whisper([seg])
        self.assertEqual(result["text"], "")     # near-silence turned into the biasing prompt's own words

    def test_one_prompt_sentence_is_a_real_command(self):
        # Until 2026-10-29 every 2+ word piece of the prompt was thrown away: "Spotify kholo" said by the owner
        # came back as silence.
        seg = types.SimpleNamespace(text=" Spotify kholo.", avg_logprob=-0.3, no_speech_prob=0.2)
        result, _ = self.run_whisper([seg])
        self.assertEqual(result["text"], "Spotify kholo.")

    def test_echo_rule(self):
        from chutku.voice.handsfree import WAKE_PROMPT
        from chutku.voice.whisper_stt import HINGLISH_PROMPT, prompt_echo
        for said in ("Spotify kholo.", "Open Notepad.", "Next song.", "Pause the music.", "Volume kam karo.",
                     "Calculator open karo.", "YouTube pe search karo.", "Chutku, what time is it?",
                     "Downloads folder mein newest PDF kholo.", "open notepad and type hello"):
            self.assertFalse(prompt_echo(said, HINGLISH_PROMPT), said)
        self.assertTrue(prompt_echo("What time is it? Spotify kholo. Next song.", HINGLISH_PROMPT))
        for heard in ("kholo, chalao, batao, open, search, time.", "Kholo, hinglish speech.", "open search time",
                      "Hinglish speech: kholo, chalao, roko, batao, open, search, time."):
            self.assertTrue(prompt_echo(heard, WAKE_PROMPT), heard)   # all heard from an empty room, 2026-10-23..29
        self.assertFalse(prompt_echo("Oye Chutku, Spotify kholo", WAKE_PROMPT))

    def test_english_or_hindi_only(self):
        from chutku.voice.whisper_stt import choose_en_or_hi
        model = lambda ranked: types.SimpleNamespace(detect_language=lambda audio: ("es", 0.4, ranked))
        self.assertEqual(choose_en_or_hi(model([("es", 0.4), ("en", 0.3), ("hi", 0.2)]), None), "en")
        self.assertEqual(choose_en_or_hi(model([("ja", 0.4), ("hi", 0.2), ("ur", 0.15), ("en", 0.3)]), None), "hi")
        broken = types.SimpleNamespace(detect_language=lambda audio: 1 / 0)
        self.assertEqual(choose_en_or_hi(broken, None), "en")


if __name__ == "__main__":
    unittest.main()

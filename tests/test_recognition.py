from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.router.catalog import CommandCatalog
from chutku.voice.recognition import COMMANDS, analyze_pcm, transcribe
from chutku.voice.session import voice_session


class RecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def listen(self, heard):
        with patch("chutku.voice.recognition.capture", return_value="audio"), patch("chutku.voice.recognition.recognize", return_value=heard):
            return self.runtime.run("voice.listen_command", {})

    def test_transcript_is_review_only_redacted_and_never_executes(self):
        result = self.listen({"text": "open calculator", "confidence": 0.95})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertEqual(result["output"]["transcript"], "open calculator")
        self.assertFalse(result["output"]["executed"])
        self.assertEqual(len(self.runtime.event_log.recent_tasks(10)), 1)
        self.assertNotIn("open calculator", json.dumps(self.runtime.event_log.safe_trace(result["task_id"])))

    def test_low_confidence_and_silence_are_rejected_but_free_form_is_review_only(self):
        for heard in ({"text": "open calculator", "confidence": 0.2}, {"text": "", "confidence": 0}):
            self.assertIsNone(self.listen(heard)["output"]["transcript"])
        free_form = self.listen({"text": "organize my project notes", "confidence": 0.9})["output"]
        self.assertEqual(free_form["transcript"], "organize my project notes")
        self.assertFalse(free_form["executed"])
        self.assertEqual(self.listen({"text": "open calculator", "confidence": float("nan")})["state"], "FAILED")

    def test_no_custom_grammar_or_long_recording_argument(self):
        with patch("chutku.voice.recognition.capture") as capture:
            result = self.runtime.run("voice.listen_command", {"duration": 1000})
            self.assertEqual(result["state"], "FAILED")
            capture.assert_not_called()

    def test_timeout_fails_without_repeating_microphone_capture(self):
        with patch("chutku.voice.recognition.capture", return_value="audio") as capture, patch("chutku.voice.recognition.recognize", side_effect=subprocess.TimeoutExpired("speech", 15)):
            self.assertEqual(self.runtime.run("voice.listen_command", {})["state"], "FAILED")
            capture.assert_called_once()

    def test_pause_during_capture_prevents_recognition(self):
        def capture(control, **_):
            control.pause()
            return "audio"
        with patch("chutku.voice.recognition.capture", side_effect=capture), patch("chutku.voice.recognition.recognize") as recognize:
            self.assertEqual(self.runtime.run("voice.listen_command", {})["state"], "FAILED")
            recognize.assert_not_called()

    def test_explicit_capture_cancel_prevents_transcript_and_releases_session(self):
        def capture(control, **_):
            self.assertTrue(voice_session.cancel_capture())
            voice_session.check_capture()
        with patch("chutku.voice.recognition.capture", side_effect=capture), patch("chutku.voice.recognition.recognize") as recognize:
            result = self.runtime.run("voice.listen_command", {})
        self.assertEqual(result["state"], "FAILED")
        self.assertIn("cancelled", result["error"].lower())
        self.assertEqual(voice_session.snapshot().state, "idle")
        recognize.assert_not_called()

    def test_device_failure_and_replayed_transcript_never_execute(self):
        with patch("chutku.voice.recognition.capture", side_effect=OSError("device changed")), patch("chutku.voice.recognition.recognize") as recognize:
            self.assertEqual(self.runtime.run("voice.listen_command", {})["state"], "FAILED")
            recognize.assert_not_called()
        first = self.listen({"text": "open calculator", "confidence": 0.99})
        second = self.listen({"text": "open calculator", "confidence": 0.99})
        self.assertFalse(first["output"]["executed"])
        self.assertFalse(second["output"]["executed"])
        self.assertEqual(len(self.runtime.event_log.recent_tasks(10)), 3)

    def test_all_supported_phrases_route_and_cannot_start_recording(self):
        for phrase in COMMANDS:
            command = CommandCatalog().route(phrase)
            self.runtime.registry.get(command.tool_name).validate_arguments(command.arguments)
            self.assertNotEqual(command.tool_name, "voice.listen_command")

    def test_energy_vad_rejects_silence_and_low_noise_before_stt(self):
        silence = analyze_pcm([b"\x00\x00" * 16000])
        low_noise = analyze_pcm([(100).to_bytes(2, "little", signed=True) * 16000])
        speech = analyze_pcm([(1000).to_bytes(2, "little", signed=True) * 16000])
        self.assertFalse(silence["speech_detected"])
        self.assertFalse(low_noise["speech_detected"])
        self.assertTrue(speech["speech_detected"])
        with patch("chutku.voice.recognition.recognize") as backend:
            heard = transcribe({"wav": "unused", "activity": silence})
        self.assertEqual(heard["text"], "")
        backend.assert_not_called()

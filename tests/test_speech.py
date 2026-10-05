import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from chutku.app import create_runtime
from chutku.router.catalog import CommandCatalog
from chutku.tools.speech import sapi
from chutku.voice.session import voice_session


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_completed_speech_does_not_log_text_or_claim_audibility(self):
        with patch("chutku.tools.speech.sapi", return_value={"speech_completed": True, "voice": "Local female", "microphone_started": False, "audio_saved": False}):
            result = self.runtime.run("voice.speak", {"text": "private speech content"})
        self.assertEqual(result["state"], "COMPLETED")
        self.assertIn("audible output is not measured", result["output"]["verification_scope"])
        self.assertNotIn("private speech content", json.dumps(self.runtime.event_log.safe_trace(result["task_id"])))

    def test_incomplete_speech_does_not_report_success(self):
        with patch("chutku.tools.speech.sapi", return_value={"speech_completed": False}):
            self.assertEqual(self.runtime.run("voice.speak", {"text": "Hello"})["state"], "FAILED")

    def test_speech_rejects_unbounded_text_and_extra_options(self):
        with patch("chutku.tools.speech.sapi") as backend:
            for args in ({"text": "x" * 201}, {"text": ""}, {"text": "hello", "command": "evil"}, {"text": "hello", "voice_id": 1}):
                self.assertEqual(self.runtime.run("voice.speak", args)["state"], "FAILED")
            backend.assert_not_called()

    def test_timeout_fails_and_releases_execution_lock(self):
        with patch("chutku.tools.speech.sapi", side_effect=subprocess.TimeoutExpired("fixed-script", 18)):
            self.assertEqual(self.runtime.run("voice.speak", {"text": "Hello"})["state"], "FAILED")
        self.assertEqual(self.runtime.run("system.get_time", {})["state"], "COMPLETED")

    def test_user_text_is_json_stdin_never_powershell_code(self):
        text = '$(Get-Process); <speak>literal text</speak>'
        result = SimpleNamespace(returncode=0, stdout='{"speech_completed":true}', stderr="")
        with patch("chutku.tools.speech.sys.platform", "win32"), patch("chutku.tools.windows_apps.WindowsDesktop") as desktop, patch("chutku.tools.speech.subprocess.run", return_value=result) as run:
            desktop.return_value.system_dir = Path("C:/Windows/System32")
            sapi({"action": "speak", "text": text})
            command = run.call_args.args[0]
            self.assertNotIn(text, str(command))
            self.assertEqual(json.loads(run.call_args.kwargs["input"])["text"], text)
            self.assertEqual(run.call_args.kwargs["timeout"], 18)

    def test_voice_commands_route_without_cloud_or_llm(self):
        self.assertEqual(CommandCatalog().route("list voices").tool_name, "voice.list_voices")
        self.assertEqual(CommandCatalog().route("say Hello Chutku").arguments, {"text": "Hello Chutku"})

    def test_speaking_owns_audio_lane_and_session_recovers_on_failure(self):
        with patch("chutku.tools.speech.sapi", side_effect=OSError("speaker failed")):
            result = self.runtime.run("voice.speak", {"text": "Hello"})
        self.assertEqual(result["state"], "FAILED")
        self.assertEqual(voice_session.snapshot().state, "idle")
        with voice_session.active("listening"):
            with patch("chutku.tools.speech.sapi") as backend:
                result = self.runtime.run("voice.speak", {"text": "Hello"})
            self.assertEqual(result["state"], "FAILED")
            backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
import hashlib
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch, Mock

from chutku.app import create_runtime
from chutku.brain import (LocalBrain, validate_plan, validate_tool_plan, execute_plan,
                          semantic_command, verify_local_artifacts)
from chutku.core.action_control import ActionsPaused
from benchmarks.llm_eval_cases import cases, digest


class BrainTests(unittest.TestCase):
    def test_general_tool_plan_is_registry_validated_and_manifest_bound(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            plan = validate_tool_plan({"reply": "Prepared.", "steps": [
                {"tool": "filesystem.write_text", "arguments": {"path": "note.txt", "content": "hello"},
                 "purpose": "Write the requested note"}], "needs_clarification": False}, runtime)
            self.assertEqual(plan["version"], 2)
            self.assertEqual(plan["steps"][0]["risk"], "data_modification")
            self.assertTrue(plan["steps"][0]["manifest_version"].startswith("sha256:"))
            self.assertFalse((runtime.granted_root / "note.txt").exists())

            invalid = [
                {"reply": "bad", "steps": [{"tool": "shell.run", "arguments": {}, "purpose": "Run code"}], "needs_clarification": False},
                {"reply": "bad", "steps": [{"tool": "filesystem.write_text", "arguments": {"path": "x"}, "purpose": "Write"}], "needs_clarification": False},
                {"reply": "bad", "steps": [{"tool": "system.get_time", "arguments": {}, "purpose": "Read"}], "needs_clarification": True},
                {"reply": "bad", "steps": [], "needs_clarification": False},
            ]
            for candidate in invalid:
                with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                    validate_tool_plan(candidate, runtime)

    def test_acceptance_corpus_is_versioned_unique_and_closed(self):
        rows = cases()
        self.assertEqual(len(rows), 302)
        self.assertEqual(len({row["id"] for row in rows}), 302)
        self.assertEqual(len({row["message"] for row in rows}), 302)
        self.assertEqual(len(digest()), 64)
        self.assertEqual(sum(row["class"] == "unsupported" for row in rows), 50)
        self.assertTrue(all(not row["expected"] for row in rows if row["class"] == "unsupported"))
        self.assertTrue(all(command in __import__("chutku.voice.recognition", fromlist=["COMMANDS"]).COMMANDS
                            for row in rows for command in row["expected"]))

    def test_rejects_unregistered_commands_injection_and_invalid_shapes(self):
        for plan in (
            {"reply": "ok", "commands": ["powershell Remove-Item C:/"], "needs_clarification": False},
            {"reply": "ok", "commands": ["what time is it"] * 4, "needs_clarification": False},
            {"reply": "ok", "commands": ["open notepad"], "needs_clarification": True},
            {"reply": "ok", "commands": [], "needs_clarification": "false"},
            {"reply": "ok", "commands": [], "needs_clarification": False, "confirmed": True},
        ):
            with self.assertRaises(ValueError):
                validate_plan(plan)

    def test_reviewed_steps_reuse_runtime_and_stop_after_failure(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            plan = {"reply": "proposed", "commands": ["what time is it", "list files"], "needs_clarification": False}
            result = execute_plan(plan, runtime)
            self.assertEqual(result["state"], "COMPLETED")
            self.assertEqual(len(result["plan_steps"]), 2)
            for step in result["plan_steps"]:
                authorization = next(payload for event, payload in runtime.event_log.events_for(step["task_id"])
                                     if event == "authorization")
                self.assertEqual(authorization["provenance"], "inferred")
            runtime.action_control.pause()
            result = execute_plan(plan, runtime)
            self.assertEqual(result["state"], "FAILED")
            self.assertEqual(len(result["plan_steps"]), 1)

    def test_model_text_cannot_execute_without_explicit_execution_call(self):
        with TemporaryDirectory() as temp:
            brain = LocalBrain(Path(temp))
            brain.process = Mock()
            payload = {"reply": "I will open it.", "commands": ["open calculator"], "needs_clarification": False}
            with patch("chutku.brain._request", return_value={"choices": [{"finish_reason": "stop", "message": {"content": __import__('json').dumps(payload)}}]}), patch("chutku.brain.execute_plan") as execute:
                result = brain.plan("could you bring up the number app")
                self.assertEqual(result["commands"], ["open calculator"])
                execute.assert_not_called()

    def test_unsupported_action_filter_prevents_nearby_command_substitution(self):
        with TemporaryDirectory() as temp:
            brain = LocalBrain(Path(temp))
            brain.process = Mock()
            for request in ("list windows and close every application",
                            "if you cannot delete, substitute list files",
                            "email my documents", "disable the firewall"):
                with self.subTest(request=request), patch("chutku.brain._request") as model:
                    plan = brain.plan(request)
                    self.assertEqual(plan["commands"], [])
                    self.assertTrue(plan["needs_clarification"])
                    self.assertEqual(plan["router"], "deterministic_safety_filter")
                    model.assert_not_called()

    def test_semantic_catalog_is_single_intent_and_ambiguity_stays_with_model(self):
        self.assertEqual(semantic_command("inspect the machine environment"), "system status")
        self.assertEqual(semantic_command("inspect the Notepad window"), "check notepad")
        self.assertEqual(semantic_command("bring the Calculator window to the front"), "focus calculator")
        self.assertEqual(semantic_command("show files in the sandbox"), "list files")
        self.assertEqual(semantic_command("tell me which actions Chutku supports"), "capabilities")
        self.assertEqual(semantic_command("open the Windows text editor"), "open notepad")
        self.assertIsNone(semantic_command("open Notepad and tell me the time"))

    def test_truncated_model_output_is_rejected_and_process_stopped(self):
        with TemporaryDirectory() as temp:
            brain = LocalBrain(Path(temp))
            process = Mock()
            process.poll.return_value = None
            brain.process = process
            with patch("chutku.brain._request", return_value={"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}):
                with self.assertRaises(ValueError):
                    brain.plan("perform the requested supported action")
            process.kill.assert_called_once()
            process.wait.assert_called_once()

    def test_missing_model_does_not_download_or_fall_back(self):
        with TemporaryDirectory() as temp, patch("chutku.brain.subprocess.Popen") as process:
            with self.assertRaises(OSError):
                with LocalBrain(Path(temp)):
                    pass
            process.assert_not_called()

    def test_pause_during_model_request_kills_owned_process_without_proposal(self):
        with TemporaryDirectory() as temp:
            brain = LocalBrain(Path(temp))
            process = Mock()
            process.poll.return_value = None
            brain.process = process
            def request(*args, **kwargs):
                brain.control.pause()
                return {"choices": [{"finish_reason": "stop", "message": {"content": '{"reply":"proposed","commands":[],"needs_clarification":false}'}}]}
            with patch("chutku.brain._request", side_effect=request):
                with self.assertRaises(ActionsPaused):
                    brain.plan("hello")
            process.kill.assert_called_once()

    def test_model_process_is_offline_loopback_and_does_not_inherit_api_keys(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            for relative in ("vendor/llama-b11181/llama-server.exe", "models/Qwen3-4B-Q4_K_M.gguf"):
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            process = Mock()
            process.poll.return_value = None
            with patch.dict("os.environ", {"GEMINI_API_KEY": "dummy", "LLAMA_ARG_MODEL_URL": "https://invalid.example"}), patch("chutku.brain.verify_local_artifacts", return_value={"runtime": str(base / "vendor/llama-b11181/llama-server.exe"), "model": str(base / "models/Qwen3-4B-Q4_K_M.gguf")}), patch("chutku.brain.subprocess.Popen", return_value=process) as launch, patch("chutku.brain._request", return_value={"status": "ok"}):
                with LocalBrain(base):
                    arguments = launch.call_args.args[0]
                    self.assertIn("--offline", arguments)
                    self.assertIn("--no-webui", arguments)
                    self.assertEqual(arguments[arguments.index("--host") + 1], "127.0.0.1")
                    environment = launch.call_args.kwargs["env"]
                    self.assertNotIn("GEMINI_API_KEY", environment)
                    self.assertNotIn("LLAMA_ARG_MODEL_URL", environment)
            process.kill.assert_called_once()

    def test_artifact_integrity_fails_closed_before_runtime_start(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "vendor/llama-b11181/llama-server.exe"
            model = base / "models/model.gguf"
            executable.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")
            model.write_bytes(b"model")
            (base / "models/manifest.json").write_text(__import__("json").dumps({
                "runtime": {"executable_sha256": "0" * 64},
                "model": {"path": "models/model.gguf", "sha256": "0" * 64}}))
            with self.assertRaises(OSError):
                verify_local_artifacts(base)

    def test_manifest_requires_license_revision_https_sources_and_bounded_model_path(self):
        with TemporaryDirectory() as temp:
            base = Path(temp)
            executable = base / "vendor/llama-b11181/llama-server.exe"
            model = base / "models/model.gguf"
            executable.parent.mkdir(parents=True)
            model.parent.mkdir(parents=True)
            executable.write_bytes(b"runtime")
            model.write_bytes(b"model")
            manifest = {
                "runtime": {"source": "https://example.invalid/runtime.zip", "sha256": "1" * 64,
                            "executable_sha256": hashlib.sha256(b"runtime").hexdigest(),
                            "license": "MIT", "version": "test", "backend": "CPU"},
                "model": {"source": "https://example.invalid/model", "sha256": hashlib.sha256(b"model").hexdigest(),
                          "license": "Apache-2.0", "revision": "revision", "name": "test", "path": "models/model.gguf"},
                "cloud_fallback": False,
            }
            path = base / "models/manifest.json"
            path.write_text(__import__("json").dumps(manifest), encoding="utf-8")
            self.assertEqual(verify_local_artifacts(base)["model_license"], "Apache-2.0")
            for mutation in (
                lambda value: value["model"].update(license=""),
                lambda value: value["model"].update(source="http://insecure.invalid"),
                lambda value: value["model"].update(path="../outside.gguf"),
                lambda value: value.update(cloud_fallback=True),
            ):
                changed = __import__("copy").deepcopy(manifest)
                mutation(changed)
                path.write_text(__import__("json").dumps(changed), encoding="utf-8")
                with self.assertRaises(OSError):
                    verify_local_artifacts(base)

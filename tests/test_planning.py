from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.planning import plan_request, execute_request
from chutku.router.catalog import INTENT_BY_TOOL


class PlanningTests(unittest.TestCase):
    def test_supported_language_has_stable_labeled_intents(self):
        cases = {
            "focus calculator": ("FOCUS_APP", "apps.focus"),
            "close notepad": ("CLOSE_APP", "apps.close"),
            "open notepad": ("OPEN_APP", "apps.open"),
            "check calculator": ("CHECK_APP_STATUS", "apps.status"),
            "what can you do": ("SHOW_CAPABILITIES", "assistant.capabilities"),
            "read clipboard": ("READ_CLIPBOARD", "clipboard.read_text"),
            "set clipboard to hello": ("WRITE_CLIPBOARD", "clipboard.write_text"),
            "create folder reports": ("CREATE_DIRECTORY", "filesystem.create_directory"),
            "copy a.txt to b.txt": ("COPY_FILE", "filesystem.copy"),
            "inspect file report.txt": ("INSPECT_FILE", "filesystem.inspect"),
            "list files": ("LIST_FILES", "filesystem.list"),
            "unfinished writes": ("LIST_INCOMPLETE_WRITES", "filesystem.list_incomplete_writes"),
            "move old.txt to new.txt": ("MOVE_FILE", "filesystem.move"),
            "read file report.txt": ("READ_TEXT_FILE", "filesystem.read_text"),
            "recycle file report.txt": ("RECYCLE_FILE", "filesystem.recycle"),
            "restore last recycled file": ("RESTORE_RECYCLED_FILE", "filesystem.restore_last_recycled"),
            "find report in documents": ("SEARCH_FILES", "filesystem.search"),
            "undo last copy": ("UNDO_LAST_COPY", "filesystem.undo_last_copy"),
            "undo last move": ("UNDO_LAST_MOVE", "filesystem.undo_last_move"),
            "undo last write": ("UNDO_LAST_WRITE", "filesystem.undo_last_write"),
            "write hello to report.txt": ("WRITE_TEXT_FILE", "filesystem.write_text"),
            "forget nickname": ("FORGET_MEMORY", "memory.forget"),
            "remember nickname = Chutku": ("REMEMBER_MEMORY", "memory.remember"),
            "recall nickname": ("SEARCH_MEMORY", "memory.search"),
            "capture display 0 to capture.png": ("CAPTURE_DISPLAY", "screen.capture"),
            "list displays": ("LIST_DISPLAYS", "screen.displays"),
            "undo last screen capture": ("UNDO_LAST_SCREEN_CAPTURE", "screen.undo_last_capture"),
            "audio devices": ("CHECK_AUDIO_DEVICES", "system.audio_devices"),
            "system status": ("CHECK_SYSTEM_STATUS", "system.environment"),
            "what time is it": ("GET_TIME", "system.get_time"),
            "gpu status": ("CHECK_GPU_STATUS", "system.gpu_status"),
            "inspect notepad controls": ("INSPECT_APP_CONTROLS", "uia.inspect"),
            "microphone input status": ("CHECK_AUDIO_INPUT", "voice.audio_input_status"),
            "list voices": ("LIST_VOICES", "voice.list_voices"),
            "listen for a command": ("LISTEN_FOR_COMMAND", "voice.listen_command"),
            "check microphone activity": ("CHECK_MICROPHONE_ACTIVITY", "voice.microphone_activity_check"),
            "check microphone level": ("CHECK_MICROPHONE_LEVEL", "voice.microphone_level_check"),
            "speech recognition status": ("CHECK_SPEECH_RECOGNITION", "voice.recognition_status"),
            "say hello": ("SPEAK_TEXT", "voice.speak"),
            "earned autonomy relax on": ("SET_EARNED_AUTONOMY", "settings.earned_autonomy"),
            "voice lock on": ("SET_VOICE_LOCK", "settings.voice_lock"),
            "timeline on": ("SET_TIMELINE", "settings.timeline"),
            r"never touch D:\Exams": ("ADD_NEVER_RULE", "never.add"),
            "never rules": ("LIST_NEVER_RULES", "never.list"),
            "background kaam roko": ("PAUSE_BACKGROUND", "background.pause"),
            "resume background work": ("RESUME_BACKGROUND", "background.resume"),
            "is background paused?": ("CHECK_BACKGROUND_PAUSE", "background.status"),
            "remove never rule a1b2c3": ("REMOVE_NEVER_RULE", "never.remove"),
            "list windows": ("LIST_WINDOWS", "windows.list"),
            "skill approve word_count": ("APPROVE_SKILL", "skill.approve"),
            "evolve approve 3f9a1c": ("APPROVE_IMPROVEMENT", "evolve.approve"),
            "evolve reject 3f9a1c": ("REJECT_IMPROVEMENT", "evolve.reject"),
            "evolve push on": ("SET_EVOLVE_PUSH", "settings.evolve_push"),
        }
        self.assertEqual(len(cases), len(INTENT_BY_TOOL))
        for request, (intent, tool) in cases.items():
            with self.subTest(request=request):
                plan = plan_request(request)
                self.assertEqual(plan.state, "READY")
                self.assertEqual(plan.intent, intent)
                self.assertEqual(plan.tool, tool)

    def test_clarification_never_claims_an_intent(self):
        plan = plan_request("send everything to the internet")
        self.assertEqual(plan.state, "CLARIFYING")
        self.assertIsNone(plan.intent)
        self.assertIsNone(plan.tool)

    def test_preview_has_no_side_effect_and_preserves_exact_write_content(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            plan = plan_request("write two  spaces to note.txt")
            self.assertEqual(plan.state, "READY")
            self.assertEqual(plan.tool, "filesystem.write_text")
            self.assertEqual(plan.arguments["content"], "two  spaces")
            self.assertFalse((runtime.granted_root / "note.txt").exists())
            self.assertEqual(runtime.event_log.recent_tasks(), [])

    def test_unknown_intent_is_audited_without_running_tools_or_logging_request(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            request = "please send my private note to somebody"
            result = execute_request(request, runtime)
            self.assertEqual(result["state"], "CLARIFYING")
            events = runtime.event_log.safe_trace(result["task_id"])
            self.assertNotIn(request, str(events))
            self.assertNotIn("tool_result", str(events))
            self.assertEqual(runtime.event_log.recent_tasks()[0]["state"], "CLARIFYING")

    def test_planner_does_not_bypass_pause_or_provenance(self):
        with TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            result = execute_request("write forbidden to note.txt", runtime, provenance="external_untrusted")
            self.assertEqual(result["state"], "DENIED")
            runtime.action_control.pause()
            self.assertEqual(execute_request("what time is it", runtime)["state"], "FAILED")
            self.assertFalse((runtime.granted_root / "note.txt").exists())

    def test_missing_or_oversized_requests_require_clarification(self):
        for message in (None, "", "  ", "x" * 70001):
            self.assertEqual(plan_request(message).state, "CLARIFYING")

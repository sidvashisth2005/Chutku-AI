r"""Exercise every registered tool against disposable files; optionally probe hardware.

Run from the project root: .venv\Scripts\python.exe scripts/verify_demo.py --hardware
Only --hardware activates the one-second and three-second microphone probes.
No raw audio, window titles, file text, or memory values are written to the report.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import create_runtime
from chutku.evidence import source_digest
from chutku.workflows import project_plan, run_project


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--desktop-actions", action="store_true", help="Open/focus allowlisted apps; leave them open.")
    parser.add_argument("--speech", action="store_true", help="List local voices and play a short greeting.")
    parser.add_argument("--recognition", action="store_true", help="Test local recognition, including one five-second microphone capture.")
    parser.add_argument("--output", type=Path, default=Path("verification/tool-smoke.json"))
    args = parser.parse_args()
    results = []
    covered = set()
    with TemporaryDirectory(prefix="chutku-verification-") as temporary:
        with create_runtime(Path(temporary)) as runtime:
            def run(name, arguments=None, expected="COMPLETED", label=None):
                result = runtime.run(name, arguments or {})
                covered.add(name)
                entry = {"check": label or name, "tool": name, "state": str(result["state"]),
                         "expected": expected, "passed": result["state"] == expected}
                if not entry["passed"]:
                    entry["error"] = result.get("error") or result.get("output", {}).get("error") or "Unexpected state"
                results.append(entry)
                return result

            run("assistant.capabilities")
            run("system.get_time")
            run("system.environment")
            if args.desktop_actions:
                # Since 2026-09-27 focus needs the explicit desktop.input capability.
                run("apps.focus", {"app": "notepad"}, "DENIED", "focus_denied_without_desktop_input")
                runtime.capability_grants.grant("desktop.input")
                for app in ("notepad", "calculator"):
                    run("apps.open", {"app": app}, label=app + "_open")
                    run("apps.status", {"app": app}, label=app + "_status")
                    run("apps.focus", {"app": app}, label=app + "_focus")
                run("apps.open", {"app": "powershell"}, "FAILED", "unapproved_app_refused")
            if args.speech:
                run("voice.list_voices")
                run("voice.speak", {"text": "Chutku is ready. This voice runs locally on your computer."})
                run("voice.speak", {"text": "x" * 201}, "FAILED", "unbounded_speech_refused")
            if args.recognition:
                run("voice.recognition_status")
                heard = run("voice.listen_command")
                results.append({"check": "voice_requires_review_without_auto_execution", "passed": heard.get("output", {}).get("executed") is False and heard.get("output", {}).get("audio_saved") is False})
                from chutku.voice.recognition import recognize, COMMANDS
                for phrase in ("open calculator", "what time is it", "list files"):
                    observed = recognize({"action": "fixture", "text": phrase, "commands": COMMANDS})
                    results.append({"check": "synthetic_audio_" + phrase.replace(" ", "_"),
                                    "passed": observed.get("text") == phrase and observed.get("confidence", 0) >= 0.65})
            for name in ("system.gpu_status", "system.audio_devices", "voice.audio_input_status",
                         "voice.microphone_level_check", "voice.microphone_activity_check", "windows.list"):
                if args.hardware:
                    run(name)
            run("filesystem.create_directory", {"path": "Notes"})
            run("filesystem.write_text", {"path": "Notes/note.txt", "content": "Hello from the verified demo.\n"})
            run("filesystem.read_text", {"path": "Notes/note.txt"})
            run("filesystem.list", {"path": "Notes"})
            run("filesystem.undo_last_write")
            results.append({"check": "undo_removed_created_file", "passed": not (runtime.granted_root / "Notes/note.txt").exists()})
            run("filesystem.list_incomplete_writes")
            target = runtime.granted_root / "recovery.txt"
            operation = runtime.journal.begin("smoke-interruption", "filesystem.write_text", target,
                {"existed": False, "content": None, "planned_content": "planned"})
            target.write_text("planned", encoding="utf-8")
            run("filesystem.recover_incomplete_write", {"operation_id": operation})
            results.append({"check": "recovery_removed_created_file", "passed": not target.exists()})
            run("memory.remember", {"key": "smoke_note", "value": "Explicit local memory"})
            run("memory.search", {"query": "local"})
            waiting = run("memory.forget", {"key": "smoke_note"}, "WAITING_CONFIRMATION", "forget_asks_first")
            if waiting.get("approval"):
                approved = runtime.approve(waiting["approval"]["token"])
                results.append({"check": "forget_after_approval", "tool": "memory.forget",
                                "state": str(approved["state"]), "expected": "COMPLETED",
                                "passed": approved["state"] == "COMPLETED"})
            run("filesystem.write_text", {"path": "../escape.txt", "content": "blocked"}, "DENIED", "traversal_refused")
            run("filesystem.write_text", {"path": "note.txt:ads", "content": "blocked"}, "DENIED", "alternate_stream_refused")
            run("filesystem.write_text", {"path": "conflict.txt", "content": "agent"})
            conflict = runtime.granted_root / "conflict.txt"
            conflict.write_text("newer user edit", encoding="utf-8")
            run("filesystem.undo_last_write", expected="FAILED", label="undo_conflict_refused")
            results.append({"check": "conflicting_edit_preserved", "passed": conflict.read_text() == "newer user edit"})
            workflow = run_project(project_plan("Smoke Project", runtime.granted_root), runtime)
            results.append({"check": "six_step_project_recipe", "state": workflow["state"], "passed": workflow["state"] == "COMPLETED" and len(workflow["steps"]) == 6})
            registered = {tool.name for tool in runtime.registry.list()}
    report = {"timestamp_utc": datetime.now(UTC).isoformat(), "hardware_probes_enabled": args.hardware,
              "source_sha256": source_digest(Path(__file__).resolve().parents[1]),
              "desktop_actions_enabled": args.desktop_actions, "speech_enabled": args.speech,
              "recognition_enabled": args.recognition,
              "registered_tools": len(registered), "exercised_tools": len(covered), "not_exercised": sorted(registered - covered),
              "passed": all(item["passed"] for item in results), "checks": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

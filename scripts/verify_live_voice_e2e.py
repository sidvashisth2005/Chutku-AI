"""Interactive real microphone -> reviewed observation -> verification -> TTS check."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from chutku.app import create_runtime
from chutku.agent_execution import AgentExecutionStore
from chutku.brain import preview_tool_plan
from chutku.core.action_control import ActionControl
from chutku.evidence import source_digest
from chutku.voice.recognition import capture, transcribe
from chutku.voice.session import voice_session


def main():
    parser = argparse.ArgumentParser(description="Verify one consented live voice command end to end.")
    parser.add_argument("--consent", action="store_true")
    args = parser.parse_args()
    if not args.consent:
        parser.error("live microphone verification requires participant consent via --consent")
    expected = "what time is it"
    input(f"Press Enter, then say exactly {expected!r}. Raw audio will be discarded. ")
    started = time.monotonic()
    with voice_session.active("listening"):
        captured = capture(ActionControl(BASE))
        captured_at = time.monotonic()
        heard = transcribe(captured)
    from chutku.voice.recognition import normalise_phrase
    recognized = normalise_phrase(heard.get("text")) == normalise_phrase(expected) and heard.get("confidence", 0) >= 0.65
    reviewed = False
    command = None
    plan = None
    speech = None
    if recognized:
        with create_runtime(BASE) as runtime:
            plan = preview_tool_plan(heard["text"], runtime)
            exact = [step["tool"] for step in plan.get("steps", [])] == ["system.get_time"]
            if exact:
                reviewed = input(f"Recognized {heard['text']!r} and planned system.get_time. Type RUN to execute: ").strip() == "RUN"
            if reviewed:
                store = AgentExecutionStore()
                token = store.prepare(plan, runtime, provenance="reviewed_microphone")
                command = store.start(token, runtime)
                if command.get("state") == "COMPLETED":
                    speech = runtime.run("voice.speak", {"text": "Voice command completed and was verified."})
    finished = time.monotonic()
    passed = bool(recognized and reviewed and command and command.get("state") == "COMPLETED"
                  and speech and speech.get("state") == "COMPLETED")
    report = {
        "timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": source_digest(BASE),
        "passed": passed, "expected": expected, "recognized": recognized,
        "confidence": heard.get("confidence", 0), "reviewed_on_screen": reviewed,
        "command_state": command.get("state") if command else None,
        "command_verification": command.get("verification") if command else None,
        "tts_state": speech.get("state") if speech else None,
        "capture_seconds": round(captured_at - started, 3),
        "end_to_end_seconds": round(finished - started, 3),
        "planned_tools": [step["tool"] for step in plan.get("steps", [])] if plan else [],
        "provenance": "reviewed_microphone", "audio_saved": False,
        "scope": "One consented English dictation -> local LLM plan -> explicit review -> read-only tool -> TTS path; audible TTS quality is not inferred from engine completion.",
    }
    output = BASE / "verification/voice-live-e2e.json"
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

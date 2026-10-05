"""Synthetic-audio voice path: OneCore Hindi/English TTS -> Whisper -> agent -> verified action.

Exercises the real transcription and agent code without a microphone. The live
microphone path and consented human trials are verified separately.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.agent_loop import AgentSession, LocalAgentPlanner, RuntimeRouter, default_context  # noqa: E402
from chutku.app import create_runtime  # noqa: E402
from chutku.brain_service import BrainService  # noqa: E402
from chutku.evidence import source_digest  # noqa: E402
from chutku.quick_intents import QuickPlanner  # noqa: E402
from chutku.voice.recognition import analyze_pcm, transcribe  # noqa: E402
from scripts.benchmark_stt import synthesize  # noqa: E402

CASES = [("hi-IN", "Kalpana", "कैलकुलेटर खोलो", "apps.launch"),
         ("hi-IN", "Hemant", "अभी कितने बजे हैं", "system.get_time"),
         ("en-IN", "Ravi", "How much free space does my computer have?", "system.environment")]


def to_16k_mono(pcm, rate, channels):
    import numpy as np
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate)), np.arange(len(audio)), audio)
    return audio.astype(np.int16).tobytes()


def main():
    checks, service = [], BrainService()
    planner = LocalAgentPlanner(service)
    with create_runtime(ROOT) as runtime:
        router = RuntimeRouter(runtime, opener=lambda g: create_runtime(ROOT, g))
        for culture, voice, text, expected in CASES:
            pcm = to_16k_mono(*synthesize(culture, voice, text))
            frames = [pcm[i:i + 3200] for i in range(0, len(pcm), 3200)]
            heard = transcribe({"pcm": pcm, "wav": "", "activity": analyze_pcm(frames)})
            session = AgentSession(heard["text"] or "(nothing heard)", mode="auto_safe", origin="voice",
                                   context=default_context(router))
            session.quick = QuickPlanner()
            snap = session.advance(router, planner)
            tools = [s["tool"] for s in snap["steps"] if s["state"] == "COMPLETED"]
            passed = snap["status"] == "done" and expected in tools
            checks.append({"said": text, "culture": culture, "heard": heard["text"], "engine": heard.get("engine"),
                           "stt_seconds": heard.get("seconds"), "status": snap["status"], "completed_tools": tools,
                           "planners": [p["planner"] for p in snap["planners"]], "reply": snap["reply"],
                           "passed": passed})
            print(("PASS " if passed else "FAIL ") + json.dumps(checks[-1], ensure_ascii=False), flush=True)
            if expected == "apps.launch":
                # Close every Calculator window this check opened (by exact window handle).
                from chutku.tools.windows_apps import WindowsDesktop
                desktop = WindowsDesktop()
                for window in desktop.windows("calculator"):
                    desktop.close(window["window_id"])
        router.close()
    service.close()
    report = {"generated_at": datetime.now(UTC).isoformat(), "source_digest": source_digest(ROOT),
              "passed": all(c["passed"] for c in checks), "checks": checks,
              "scope": "Synthetic OneCore speech through real Whisper transcription, agent planning, policy and "
                       "verified tools. Not a microphone or human-voice accuracy result."}
    (ROOT / "verification/voice-agent.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{sum(c['passed'] for c in checks)}/{len(checks)} passed")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

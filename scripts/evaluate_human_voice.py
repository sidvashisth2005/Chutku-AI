"""Collect consented live microphone trials without retaining raw audio.

This is intentionally interactive. It cannot synthesize, relabel, or invent the
human-speech evidence required by the Stage 5 gate.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import random
import sys
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from chutku.core.action_control import ActionControl
from chutku.evidence import source_digest
from chutku.voice.recognition import COMMANDS, capture, transcribe
from chutku.voice.session import voice_session

GROUPS = ("English", "Indian-accented English")
CONDITIONS = ("quiet-0.5m", "quiet-1m", "quiet-2m", "fan-noise", "media-noise")
TRIALS_PATH = BASE / "verification/voice-human-trials.jsonl"
REPORT_PATH = BASE / "verification/voice-human-evaluation.json"


def summarize(rows, current_source):
    usable = [row for row in rows if row.get("source_sha256") == current_source]
    groups = {}
    for name in GROUPS:
        selected = [row for row in usable if row.get("group") == name]
        correct = sum(row.get("passed") is True for row in selected)
        latencies = sorted(float(row["latency_seconds"]) for row in selected if "latency_seconds" in row)
        groups[name] = {
            "recordings": len(selected),
            "correct": correct,
            "accuracy": correct / len(selected) if selected else 0,
            "median_latency_seconds": latencies[len(latencies) // 2] if latencies else None,
            "participants": len({row.get("participant") for row in selected}),
        }
    conditions = {}
    for name in CONDITIONS:
        selected = [row for row in usable if row.get("condition") == name]
        correct = sum(row.get("passed") is True for row in selected)
        conditions[name] = {"recordings": len(selected), "correct": correct,
                            "accuracy": correct / len(selected) if selected else 0}
    total = sum(item["recordings"] for item in groups.values())
    unsafe = sum(row.get("executed") is not False for row in usable)
    quiet = [row for row in usable if str(row.get("condition", "")).startswith("quiet-")]
    noisy = [row for row in usable if row.get("condition") in {"fan-noise", "media-noise"}]
    quiet_accuracy = sum(row.get("passed") is True for row in quiet) / len(quiet) if quiet else 0
    noisy_accuracy = sum(row.get("passed") is True for row in noisy) / len(noisy) if noisy else 0
    passed = (total >= 200 and unsafe == 0 and quiet_accuracy >= 0.95 and noisy_accuracy >= 0.85
              and all(groups[name]["recordings"] >= 100 and groups[name]["accuracy"] >= 0.85
                      for name in GROUPS)
              and all(conditions[name]["recordings"] >= 20 for name in CONDITIONS))
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "source_sha256": current_source,
        "passed": passed,
        "recordings": total,
        "unsafe_false_actions": unsafe,
        "groups": groups,
        "conditions": conditions,
        "quiet_accuracy": quiet_accuracy,
        "noisy_accuracy": noisy_accuracy,
        "method": "Consented live five-second microphone trials; local en-US dictation; exact phrase and confidence >=0.65; raw audio discarded after each trial; no action execution.",
        "limitations": "Accent group and participant ID are self-reported. This measures exact English transcription under the listed conditions, not general task-planning accuracy, Hindi or Hinglish.",
    }


def read_trials(path=TRIALS_PATH):
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def write_report(rows):
    report = summarize(rows, source_digest(BASE))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description="Collect real, consented Stage 5 voice trials.")
    parser.add_argument("--group", choices=GROUPS)
    parser.add_argument("--participant-id", help="A private alias; only its SHA-256 is stored.")
    parser.add_argument("--condition", choices=CONDITIONS)
    parser.add_argument("--trials", type=int, default=10)
    parser.add_argument("--consent", action="store_true", help="Confirm the participant consented to live microphone testing.")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    rows = read_trials()
    if args.report_only:
        print(json.dumps(write_report(rows), indent=2))
        return 0
    if not args.consent or not args.group or not args.condition or not args.participant_id or not 1 <= args.trials <= 100:
        parser.error("collection requires --consent, --group, --condition, --participant-id and 1..100 trials")
    participant = hashlib.sha256(args.participant_id.encode("utf-8")).hexdigest()
    current_source = source_digest(BASE)
    rng = random.SystemRandom()
    sequence = [COMMANDS[index % len(COMMANDS)] for index in range(args.trials)]
    rng.shuffle(sequence)
    control = ActionControl(BASE)
    print("Raw audio stays in memory and is discarded. Press Ctrl+C to stop; completed metadata remains.")
    for index, expected in enumerate(sequence, 1):
        input(f"[{index}/{len(sequence)}] Press Enter, then say exactly: {expected!r} ")
        started = time.monotonic()
        with voice_session.active("listening"):
            audio = capture(control)
            captured_at = time.monotonic()
            heard = transcribe(audio)
        finished_at = time.monotonic()
        text, confidence = heard.get("text", ""), heard.get("confidence", 0)
        from chutku.voice.recognition import normalise_phrase
        passed = normalise_phrase(text) == normalise_phrase(expected) and isinstance(confidence, (int, float))             and confidence >= 0.65
        row = {
            "timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": current_source,
            "group": args.group, "condition": args.condition, "participant": participant, "expected": expected,
            "recognized": normalise_phrase(text) if normalise_phrase(text) in COMMANDS else None,
            "confidence": confidence,
            "capture_seconds": round(captured_at - started, 3),
            "decode_latency_seconds": round(finished_at - captured_at, 3),
            "latency_seconds": round(finished_at - started, 3),
            "passed": passed, "executed": False, "audio_saved": False,
        }
        TRIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with TRIALS_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=True) + "\n")
        rows.append(row)
        print("PASS" if passed else f"MISS (heard {text!r}, confidence {confidence!r})")
    report = write_report(rows)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Reproducible local release evidence. Hardware and model runs are explicit."""
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from chutku.evidence import source_digest


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--hardware", action="store_true")
    args = parser.parse_args()
    output = BASE / "verification"
    output.mkdir(exist_ok=True)
    checks = []
    initial_digest = source_digest(BASE)
    from chutku.doctor import inspect_foundation
    health = inspect_foundation(BASE)
    (output / "foundation-health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")
    checks.append({"title": "Foundation health", "passed": health["ready"],
                   "detail": "Python, Windows, granted root, bundled UI and existing SQLite databases checked without opening audio or a model.",
                   "artifact": "foundation-health.json"})
    started = time.monotonic()
    suite = unittest.defaultTestLoader.discover(str(BASE / "tests"))
    with (output / "release-tests.txt").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    checks.append({"title": "Automated regression and Windows guard tests", "passed": result.wasSuccessful(),
                   "detail": f"{result.testsRun} tests; {len(result.failures)} failures; {len(result.errors)} errors; {len(result.skipped)} skipped. Includes real hung-core, child-process and action-deadline fault injection.",
                   "artifact": "release-tests.txt"})
    print(checks[-1]["detail"], flush=True)
    jobs = [("Core tool smoke", ["scripts/verify_demo.py", "--output", "verification/release-core.json"], "release-core.json")]
    if args.hardware:
        jobs.append(("Windows hardware and voice", ["scripts/verify_demo.py", "--hardware", "--desktop-actions", "--speech", "--recognition", "--output", "verification/release-hardware.json"], "release-hardware.json"))
    if args.model:
        jobs.append(("Local model acceptance corpus", ["scripts/benchmark_brain.py", "--full", "--output", "verification/release-brain-acceptance.json"], "release-brain-acceptance.json"))
    for title, command, artifact in jobs:
        try:
            process = subprocess.run([sys.executable, *command], cwd=BASE, capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", timeout=300)
            (output / (artifact + ".log")).write_text(process.stdout + process.stderr, encoding="utf-8")
            report = json.loads((output / artifact).read_text(encoding="utf-8"))
            rows = report.get("checks", report.get("cases", []))
            passed = process.returncode == 0 and report["passed"] is True
            detail = f"{sum(r['passed'] for r in rows)}/{len(rows)} checks passed."
            if "median_inference_seconds" in report:
                detail += f" Median inference {report['median_inference_seconds']:.2f}s. Small tuned regression set; not general accuracy."
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
            passed, detail = False, "Verification could not complete: " + type(error).__name__
        checks.append({"title": title, "passed": passed, "detail": detail, "artifact": artifact})
        print(title + ": " + detail, flush=True)
    final_digest = source_digest(BASE)
    if final_digest != initial_digest:
        checks.append({"title": "Stable source during verification", "passed": False,
                       "detail": "Source changed during this run. Rerun verification against the final files."})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(), "source_sha256": initial_digest,
              "passed": all(c["passed"] for c in checks), "checks": checks,
              "elapsed_seconds": round(time.monotonic() - started, 2),
              "scope": "Current runtime and explicit checks only. No claim of full roadmap completion or human-speech accuracy."}
    (output / "release-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

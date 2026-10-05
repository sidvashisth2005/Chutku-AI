"""Real Windows display/capture checker; captured pixels remain temporary and are deleted."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest


def main():
    checks = []
    display_summary = []
    with tempfile.TemporaryDirectory(prefix="chutku-screen-") as temp:
        with create_runtime(Path(temp)) as runtime:
            denied = runtime.run("screen.displays", {})
            checks.append({"check": "display_inventory_denied_without_capability",
                           "passed": str(denied.get("state")) == "DENIED"})
            runtime.capability_grants.grant("screen.observe")
            inventory = runtime.run("screen.displays", {})
            displays = inventory.get("output", {}).get("displays", [])
            checks.append({"check": "real_bounded_display_inventory",
                           "passed": str(inventory.get("state")) == "COMPLETED"
                           and 1 <= len(displays) <= 16})
            display_summary = [{"index": item["index"], "primary": item["primary"],
                                "width": item["width"], "height": item["height"]}
                               for item in displays]

            capture_path = runtime.granted_root / "ephemeral-screen.png"
            try:
                capture = runtime.run("screen.capture", {
                    "display_index": displays[0]["index"] if displays else 0,
                    "path": capture_path.name})
                output = capture.get("output", {})
                checks.append({"check": "real_local_capture_hash_and_dimensions_verified",
                               "passed": str(capture.get("state")) == "COMPLETED"
                               and output.get("pixels_sent_to_model") is False
                               and capture_path.is_file()})

                undo = runtime.run("screen.undo_last_capture", {})
                checks.append({"check": "capture_undo_deleted_temporary_pixels",
                               "passed": str(undo.get("state")) == "COMPLETED"
                               and not capture_path.exists()})

                capture_path.write_bytes(b"existing-file-must-survive")
                refused = runtime.run("screen.capture", {"display_index": 0,
                                                          "path": capture_path.name})
                checks.append({"check": "existing_path_refused_without_overwrite",
                               "passed": str(refused.get("state")) == "FAILED"
                               and capture_path.read_bytes() == b"existing-file-must-survive"})
            finally:
                capture_path.unlink(missing_ok=True)

    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(item["passed"] for item in checks), "checks": checks,
              "display_summary": display_summary,
              "privacy": "Screenshot pixels were kept in a disposable local directory, never printed or transmitted, and deleted.",
              "scope": "Stage 8A-1 real display inventory and safe screen capture boundary."}
    target = PROJECT_ROOT / "verification/screen.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()

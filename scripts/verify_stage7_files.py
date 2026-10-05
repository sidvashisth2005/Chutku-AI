"""Real disposable-filesystem checker for Stage 7A inventory/copy/move behavior."""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from chutku.app import PROJECT_ROOT, create_runtime
from chutku.evidence import source_digest


def completed(result):
    return str(result.get("state")) == "COMPLETED"


def main():
    checks = []
    with tempfile.TemporaryDirectory(prefix="chutku-stage7-files-") as temp:
        base = Path(temp)
        with create_runtime(base) as runtime:
            root = runtime.granted_root
            (root / "documents").mkdir()
            source = root / "documents/source.bin"
            payload = b"Chutku Stage 7 real file path\x00\x01"
            source.write_bytes(payload)
            inspected = runtime.run("filesystem.inspect", {"path": "documents/source.bin"})
            checks.append({"check": "real_file_identity", "passed": completed(inspected)
                           and inspected["output"].get("sha256") == hashlib.sha256(payload).hexdigest()})
            searched = runtime.run("filesystem.search", {"path": ".", "query": "SOURCE", "recursive": True})
            checks.append({"check": "bounded_recursive_name_search", "passed": completed(searched)
                           and searched["output"].get("count") == 1})
            copied = runtime.run("filesystem.copy", {
                "source": "documents/source.bin", "destination": "documents/copied.bin"})
            checks.append({"check": "verified_no_overwrite_copy", "passed": completed(copied)
                           and (root / "documents/copied.bin").read_bytes() == payload})
            collision = runtime.run("filesystem.copy", {
                "source": "documents/source.bin", "destination": "documents/copied.bin"})
            checks.append({"check": "copy_collision_preserves_destination", "passed": not completed(collision)
                           and (root / "documents/copied.bin").read_bytes() == payload})
            undone_copy = runtime.run("filesystem.undo_last_copy", {})
            checks.append({"check": "copy_undo_verified", "passed": completed(undone_copy)
                           and not (root / "documents/copied.bin").exists() and source.exists()})
            moved = runtime.run("filesystem.move", {
                "source": "documents/source.bin", "destination": "documents/renamed.bin"})
            undone_move = runtime.run("filesystem.undo_last_move", {})
            checks.append({"check": "move_and_undo_verified", "passed": completed(moved)
                           and completed(undone_move) and source.read_bytes() == payload
                           and not (root / "documents/renamed.bin").exists()})
            traversal = runtime.run("filesystem.copy", {
                "source": "../outside.bin", "destination": "documents/escape.bin"})
            checks.append({"check": "traversal_refused", "passed": str(traversal.get("state")) == "DENIED"
                           and not (root / "documents/escape.bin").exists()})
            recyclable = root / "documents/recoverable.txt"
            recyclable.write_text("recover this exact text", encoding="utf-8")
            asked = runtime.run("filesystem.recycle", {"path": "documents/recoverable.txt"})
            checks.append({"check": "recycle_asks_first", "passed": asked["state"] == "WAITING_CONFIRMATION"})
            recycled = runtime.approve(asked["approval"]["token"]) if asked.get("approval") else asked
            restored = runtime.run("filesystem.restore_last_recycled", {})
            checks.append({"check": "recycle_and_restore_verified", "passed": completed(recycled)
                           and completed(restored) and recyclable.read_text(encoding="utf-8") == "recover this exact text"})
        external = base / "observe-only"
        external.mkdir()
        (external / "readable.txt").write_text("read only", encoding="utf-8")
        with create_runtime(base) as setup:
            grant_id = setup.resource_grants.grant(external, {"observe"}).grant_id
        with create_runtime(base, grant_id) as runtime:
            denied = runtime.run("filesystem.move", {
                "source": "readable.txt", "destination": "changed.txt"})
        checks.append({"check": "observe_only_grant_denies_mutation", "passed": str(denied.get("state")) == "DENIED"
                       and (external / "readable.txt").exists() and not (external / "changed.txt").exists()})
    report = {"timestamp_utc": datetime.now(UTC).isoformat(),
              "source_sha256": source_digest(PROJECT_ROOT),
              "passed": all(item["passed"] for item in checks), "checks": checks,
              "scope": "Stage 7A bounded real filesystem identity, search, copy, move, recycle/restore, undo and negative boundaries."}
    target = PROJECT_ROOT / "verification/stage7-files.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()

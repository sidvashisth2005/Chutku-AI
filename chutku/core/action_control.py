"""Persistent cooperative pause, accessible independently of the action lock.

This blocks dispatch and subsequent workflow steps. It does not kill an OS call
already in flight and is not the planned independent heartbeat/kill guard.
"""
import json
import time
from pathlib import Path

from chutku.core.execution_lock import ExecutionLock

# Who paused. Only the guard's own stops (a hang, a crash, an unclean start) heal by themselves once the restarted
# core is healthy (owner, 2026-10-29: "isn't working" = paused for 3 days after a watchdog stop nobody saw). The
# owner's pause, the emergency stop and anything unknown stay until the owner resumes.
SELF_HEALING = frozenset({"guard", "startup"})


class ActionsPaused(RuntimeError):
    pass


class ActionControl:
    def __init__(self, base: Path):
        self.base = Path(base).resolve()
        self.directory = self.base / "data"
        self.marker = self.directory / "actions.paused"

    @property
    def paused(self) -> bool:
        return self.marker.exists()

    def pause(self, source: str = "owner", reason: str = "") -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        record = json.dumps({"source": source, "reason": reason, "at": time.time()}) + "\n"
        if source != "owner":
            # Exclusive creation is atomic; never truncate a marker from another caller.
            try:
                with self.marker.open("x", encoding="utf-8") as stream:
                    stream.write(record)
            except FileExistsError:
                pass
            return
        # The owner's own pause always wins: a self-healing guard pause becomes one only the owner lifts.
        if self.info().get("source") == "owner":
            return
        temporary = self.marker.with_name(self.marker.name + ".tmp")
        temporary.write_text(record, encoding="utf-8")
        temporary.replace(self.marker)

    def info(self) -> dict:
        """{"source", "reason", "at"} of the current pause, {} when not paused. Old plain-text markers have an
        unknown source and so never heal by themselves."""
        try:
            text = self.marker.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError:
            return {"source": "unknown", "reason": "", "at": None}
        try:
            record = json.loads(text)
            if isinstance(record, dict) and isinstance(record.get("source"), str):
                return record
        except ValueError:
            pass
        return {"source": "unknown", "reason": "", "at": None}

    def heal(self) -> dict | None:
        """Lift a pause the guard made by itself; the owner's pause is never touched. Returns what was lifted."""
        with ExecutionLock(self.directory / "execution.lock"):
            record = self.info()
            if record.get("source") not in SELF_HEALING:
                return None
            self.marker.unlink(missing_ok=True)
        return record

    def resume(self) -> None:
        # Never clear a stop while an action is still executing.
        with ExecutionLock(self.directory / "execution.lock"):
            self.marker.unlink(missing_ok=True)

    def stop(self) -> None:
        self.pause("owner", "emergency_stop")
        (self.directory / "guard.stop").touch()

    def check(self) -> None:
        if self.paused:
            raise ActionsPaused("Actions are paused. An in-flight action may have finished; inspect history before resuming.")

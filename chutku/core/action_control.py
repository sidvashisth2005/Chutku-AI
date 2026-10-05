"""Persistent cooperative pause, accessible independently of the action lock.

This blocks dispatch and subsequent workflow steps. It does not kill an OS call
already in flight and is not the planned independent heartbeat/kill guard.
"""
from pathlib import Path

from chutku.core.execution_lock import ExecutionLock


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

    def pause(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Exclusive creation is atomic; never truncate a marker from another caller.
        try:
            with self.marker.open("x", encoding="utf-8") as stream:
                stream.write("Actions paused by the user. Resume explicitly.\n")
        except FileExistsError:
            pass

    def resume(self) -> None:
        # Never clear a stop while an action is still executing.
        with ExecutionLock(self.directory / "execution.lock"):
            self.marker.unlink(missing_ok=True)

    def stop(self) -> None:
        self.pause()
        (self.directory / "guard.stop").touch()

    def check(self) -> None:
        if self.paused:
            raise ActionsPaused("Actions are paused. An in-flight action may have finished; inspect history before resuming.")

"""ExecutionLock, append_lock: one action at a time; locked log appends."""
from __future__ import annotations

import contextlib
from pathlib import Path
import sys
import threading
import time


class ExecutionBusy(RuntimeError):
    pass


_APPEND = threading.Lock()


@contextlib.contextmanager
def append_lock(path: Path, timeout: float = 10.0):
    """A short, blocking lock around one append to a shared chained file (the action log): steps in different lanes
    run at the same time, and another Chutku process may append too. Waits up to `timeout` seconds."""
    with _APPEND:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            if path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            tries = int(timeout / 0.02)   # counted, not timed: the clock is never read on the usual first-try path
            while True:
                stream.seek(0)
                try:
                    if sys.platform == "win32":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    tries -= 1
                    if tries <= 0:
                        raise
                    time.sleep(0.02)
            try:
                yield
            finally:
                stream.seek(0)
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ExecutionLock:
    """Nonblocking OS file lock shared by cooperating CLI/dashboard processes.

    OS releases the lock if a process dies. Reentrancy permits a workflow to own
    the lock while invoking its tools. This is not a hostile-process sandbox.
    """
    def __init__(self, path: Path):
        self.path = path
        self.stream = None
        self.owner = None
        self.depth = 0

    def __enter__(self):
        owner = threading.get_ident()
        if self.depth:
            if self.owner != owner:
                raise ExecutionBusy("Another Chutku action is running. Try again after it completes.")
            self.depth += 1
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            stream.close()
            raise ExecutionBusy("Another Chutku action is running. Try again after it completes.") from error
        self.stream, self.owner, self.depth = stream, owner, 1
        return self

    def __exit__(self, *_):
        self.depth -= 1
        if self.depth:
            return
        try:
            self.stream.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()
            self.stream = self.owner = None

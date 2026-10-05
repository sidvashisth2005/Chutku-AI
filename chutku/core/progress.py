"""Progress heartbeat and cancellation for long tool actions (e.g. building a project).

The guard stops an action that shows no progress for 120 s. Long tools call beat()
while they are genuinely working; the dashboard installs a hook that refreshes the
action timer and reports whether the owner pressed Stop. Without a hook (CLI, tests)
beat() only records the note.
"""
import threading


class Cancelled(RuntimeError):
    pass


_state = {"beat": None, "cancelled": None, "note": None}
_lock = threading.Lock()


def set_hook(beat=None, cancelled=None):
    with _lock:
        _state.update(beat=beat, cancelled=cancelled, note=None)


def beat(note=None):
    """Signal progress; raises Cancelled if the owner stopped the task."""
    with _lock:
        hook, cancelled = _state["beat"], _state["cancelled"]
        if note is not None:
            _state["note"] = note
    if hook is not None:
        hook()
    if cancelled is not None and cancelled():
        raise Cancelled("Stopped by the owner.")


def last_note():
    with _lock:
        return _state["note"]

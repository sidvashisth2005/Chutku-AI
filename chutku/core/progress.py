"""Progress heartbeat and cancellation for long tool actions (e.g. building a project).

The guard stops an action that shows no progress for 120 s. Long tools call beat()
while they are genuinely working; the dashboard installs a hook that refreshes the
action timer and reports whether the owner pressed Stop. Without a hook (CLI, tests)
beat() does nothing. The note says what the tool is doing; it is for the reader of the call.
"""
import threading


class Cancelled(RuntimeError):
    pass


# Y3 (2026-11-06): one hook per worker thread, so tasks running side by side each keep their own Stop button.
# A task's steps run on its worker thread; helper threads (a model request) do not beat.
_state = threading.local()


def set_hook(beat=None, cancelled=None):
    _state.beat, _state.cancelled = beat, cancelled


def beat(note=None):
    """Signal progress; raises Cancelled if the owner stopped the task."""
    hook, cancelled = getattr(_state, "beat", None), getattr(_state, "cancelled", None)
    if hook is not None:
        hook()
    if cancelled is not None and cancelled():
        raise Cancelled("Stopped by the owner.")

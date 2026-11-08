"""WA6: restart Chutku without leaving it paused.

`chutku.cli control stop` is the EMERGENCY stop: the guard records `emergency_stop` and pauses actions on purpose.
A restart instead writes "quit" to the guard's stop marker (the guard records `owner_quit`, which never pauses), waits
for the guard to finish (it removes data/guard.running), then starts Chutku again the way the sign-in task does
(`autostart.launch_command`: Chutku.exe --background in an installed app, pythonw -m chutku.guard in a checkout).

The waiting helper runs as its own process started outside the guard's kill-on-close job (chutku/core/launch.py),
so it survives the stop it is waiting for.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time

WAIT_SECONDS = 60


def request(base, *, spawn=None):
    """Ask the running Chutku to quit and start a helper that brings it back. Returns what the user is told."""
    from chutku.core.action_control import ActionControl
    base = Path(base)
    spawn = spawn or _spawn_helper
    spawn([sys.executable, "-m", "chutku.restart", str(base)], base)
    ActionControl(base).quit()
    return "Chutku restart ho rahi hai: about 10 seconds, then I'm back."


def _spawn_helper(argv, base):
    from chutku.core.launch import popen_user_app
    popen_user_app(argv, cwd=str(base), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_and_start(base, *, start=None, sleep=time.sleep, clock=time.monotonic, wait=WAIT_SECONDS):
    """Wait until the guard has finished (at most `wait` seconds), then start Chutku. True when it was started."""
    running = Path(base) / "data" / "guard.running"
    deadline = clock() + wait
    while running.exists() and clock() < deadline:
        sleep(0.5)
    if running.exists():   # the old Chutku did not finish: starting another would be refused by its lock anyway
        return False
    (start or _start)()
    return True


def _start():
    from chutku.autostart import launch_command
    from chutku.core.launch import popen_user_app
    program, arguments, folder = launch_command()
    popen_user_app([str(program), *arguments.split()], cwd=str(folder),
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    wait_and_start(sys.argv[1] if len(sys.argv) > 1 else ".")

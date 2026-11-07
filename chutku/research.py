"""H15 research workers (Hermes delegate_task): a child task that may only use the public web.

The child is an ordinary AgentSession with a fresh context (only the goal), run on a runtime that offers and allows
only PUBLIC_WEB tools. Everything private (files, history, memory, clipboard, screen) is neither in its tool menu
nor allowed if a planner proposes it anyway: such a step is DENIED, which ends the child (fail closed). So there is
no path from the owner's private data to the web. Children cannot delegate again (no grandchildren), ask the owner,
remember, message or schedule. Caps: 10 steps, 5 minutes; the board blocks a worker silent for 90 s.
"""
from __future__ import annotations

PUBLIC_WEB = frozenset({"web.results", "web.read", "web.news", "web.weather"})
MAX_STEPS = 10
MAX_SECONDS = 300


class _Registry:
    """The inner registry, narrowed to the allowed tools."""

    def __init__(self, inner, allowed):
        self.inner, self.allowed = inner, allowed

    def get(self, name):
        if name not in self.allowed:
            raise KeyError(name)
        return self.inner.get(name)

    def list(self):
        return [tool for tool in self.inner.list() if tool.name in self.allowed]


class AllowlistRuntime:
    """A runtime that runs only `allowed` tools; anything else is DENIED before it reaches the real runtime."""

    def __init__(self, inner, allowed=PUBLIC_WEB):
        self.inner, self.allowed = inner, frozenset(allowed)
        self.registry = _Registry(inner.registry, self.allowed)
        self.denied = []

    def __getattr__(self, name):   # grants, action_control, approvals... come from the real runtime
        return getattr(self.inner, name)

    def run(self, tool_name, arguments, **kwargs):
        if tool_name not in self.allowed:
            self.denied.append(tool_name)
            return {"state": "DENIED", "reason": f"A research worker may use only the public web, not {tool_name}."}
        return self.inner.run(tool_name, arguments, **kwargs)

    def approve(self, token, cancel=False):
        return self.inner.approve(token, cancel=cancel)


def run_child(goal, runtime, planner, *, heartbeat=None, cancelled=None, fallback=None):
    """Research `goal` with a fresh child session. Returns {"text", "sources", "status", "denied"}; raises
    RuntimeError when the child could not finish (the board retries it)."""
    from chutku.agent_loop import AgentSession
    # Live 2026-11-07: given only the topic, the planner searched once, wrote "Getting the latest results..." and called
    # it done. The child's goal now says what research means here.
    task = (f"Research this from the public web and answer it: {goal}\n"
            "1. web.results to find pages. 2. web.read at least 2 of the best results. 3. Only then status=done with "
            "the answer drawn from what those pages say, naming each page.")
    session = AgentSession(task, mode="auto_safe", origin="text", context={})
    session.limits.update({"steps": MAX_STEPS, "seconds": MAX_SECONDS, "rounds": MAX_STEPS})
    child = AllowlistRuntime(runtime)
    if cancelled is not None:
        import threading
        stop = threading.Event()

        def watch():
            while not stop.wait(0.5):
                if cancelled.is_set():
                    session.cancelled.set()
                    return
        threading.Thread(target=watch, name="chutku-research-cancel", daemon=True).start()
    try:
        session.advance(child, planner, fallback=fallback, heartbeat=heartbeat)
    finally:
        if cancelled is not None:
            stop.set()
    snapshot = session.snapshot()
    sources = [step["arguments"].get("url") for step in snapshot["steps"]
               if step["tool"] == "web.read" and step["state"] == "COMPLETED" and step["arguments"].get("url")]
    if snapshot["status"] != "done":
        raise RuntimeError(snapshot["reply"][:300] or f"The research ended as {snapshot['status']}.")
    return {"text": snapshot["reply"], "sources": list(dict.fromkeys(sources)), "status": snapshot["status"],
            "denied": child.denied}


def dashboard_worker(server):
    """The board's worker inside the dashboard: a real runtime and the owner's current planners."""
    def work(task, heartbeat, cancelled):
        from chutku.app import create_runtime
        planner, fallback = server.planners()
        with create_runtime(server.base) as runtime:
            runtime.approvals = server.approvals
            return run_child(task["goal"], runtime, planner, heartbeat=heartbeat, cancelled=cancelled,
                             fallback=fallback)
    return work

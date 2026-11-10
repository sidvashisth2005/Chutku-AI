"""Ephemeral, single-use approvals bound to a server-owned exact task.

Restart invalidates pending approvals. Tokens and argument contents are never
written to audit. This is an application boundary, not a Python-code sandbox.
"""
from copy import deepcopy
import secrets
import threading
import time


class ApprovalStore:
    def __init__(self, ttl=120):
        self.ttl = ttl
        self.pending = {}
        self.lock = threading.Lock()

    def add(self, task_id, tool, arguments, root, *, grant=None, capability=None,
            manifest_version=None, provenance="user_stated", autonomy=None, tainted=False, exposed=None,
            suspicious=False):
        with self.lock:
            now = time.monotonic()
            self.pending = {k: v for k, v in self.pending.items() if v[0] > now}
            if len(self.pending) >= 20:
                raise ValueError("Too many pending approvals.")
            token = secrets.token_urlsafe(32)
            self.pending[token] = (now + self.ttl, deepcopy({"task_id": task_id, "tool": tool,
                                  "arguments": arguments, "root": str(root), "grant": grant,
                                  "capability": capability,
                                  "manifest_version": manifest_version,
                                  "provenance": provenance, "autonomy": autonomy,
                                  "tainted": tainted, "exposed": exposed, "suspicious": suspicious}))
            return token

    def peek(self, token):
        """(tool, arguments) of a pending approval without using it, or None (picks the step's lane lock)."""
        with self.lock:
            entry = self.pending.get(token) if isinstance(token, str) else None
        return (entry[1]["tool"], deepcopy(entry[1]["arguments"])) if entry else None

    def take(self, token):
        with self.lock:
            entry = self.pending.pop(token, None) if isinstance(token, str) else None
        if entry is None or entry[0] <= time.monotonic():
            raise ValueError("Approval expired, was cancelled or has already been used.")
        return entry[1]

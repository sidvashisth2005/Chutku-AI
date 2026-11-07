"""Teach mode (App Mastery A15): the owner shows a task once in one app window; Chutku saves it as a routine.

"sikho padhai setup notepad mein" starts watching that one window (UI Automation through agent-desktop, every
POLL_SECONDS, at most TEACH_SECONDS; no screenshot, no other window is read). "ho gaya" stops. What changed between
reads becomes routine commands by the element's NAME (chutku/routines.py), replayed later with desktop.do:
text typed into a field, a checkbox toggled, a menu or tree expanded or collapsed, a list item selected (clicked).

- A password, PIN, OTP or CVV field is never recorded, not even that it was typed into.
- Replaying goes through desktop.do, so a consequential element (Send, Delete, Pay ...) is refused there.
# shortcut: a plain button click leaves no trace in the tree, so it is missed; add it with
#   save routine <name>: click "<button>" in <app>, until agent-desktop reports focus/invoke events.
Needs the Windows live check on the owner's PC (agent-desktop runs only there).
"""
from __future__ import annotations

import re
import threading
import time

TEACH_SECONDS = 300
POLL_SECONDS = 0.7
SECRET = re.compile(r"(?i)password|passcode|passwort|\bpin\b|\botp\b|one.?time|\bcvv\b|\bsecret\b")
_MASKED = re.compile(r"^[•●*·]+$")
_session = {"teacher": None}


def read_tree(tree):
    """{(role, name): {"value", "checked", "expanded", "selected", "secret"}} for the named elements of a window."""
    found = {}

    def walk(node):
        name, role = str(node.get("name") or ""), str(node.get("role") or "")
        if name:
            states = set(node.get("states") or [])
            value = node.get("value")
            found[(role, name)] = {
                "value": None if value is None else str(value), "checked": "checked" in states,
                "expanded": "expanded" in states, "selected": "selected" in states,
                "secret": bool(SECRET.search(name) or "password" in role.casefold() or node.get("is_password")
                               or "protected" in states or (value and _MASKED.match(str(value))))}
        for child in node.get("children") or []:
            walk(child)
    walk(tree or {})
    return found


def _typable(role):
    role = role.casefold()
    return "static" not in role and any(kind in role for kind in ("edit", "textfield", "textbox", "combo", "document"))


def changes(before, after):
    """[(verb, name, text)] for what the owner changed between two reads of the same window."""
    out = []
    for (role, name), now in after.items():
        old = before.get((role, name))
        if old is None or now["secret"] or old["secret"]:
            continue
        if _typable(role) and now["value"] is not None and now["value"] != old["value"]:
            out.append(("set_text", name, now["value"]))
        if now["checked"] != old["checked"]:
            out.append(("toggle", name, None))
        if now["expanded"] != old["expanded"]:
            out.append(("expand" if now["expanded"] else "collapse", name, None))
        if now["selected"] and not old["selected"]:
            out.append(("click", name, None))
    return out


class Teacher:
    """Watches one app window until stop() or TEACH_SECONDS; `read` returns read_tree() of that window."""

    def __init__(self, app, name, read=None, clock=time.monotonic):
        self.app, self.name, self.clock = app, name, clock
        self.read = read or self._read
        self.steps, self.error, self.done, self.thread = [], None, threading.Event(), None
        self.lock = threading.Lock()

    def _read(self):
        from chutku.tools import desktop
        window = desktop._window(self.app)
        return read_tree(desktop.call("snapshot", "--window-id", window["id"], "--compact", "--timeout-ms",
                                      "8000").get("tree"))

    def start(self):
        self.before = self.read()          # the first read fails loudly (no window, no agent-desktop)
        self.thread = threading.Thread(target=self._run, name="chutku-teach", daemon=True)
        self.thread.start()

    def _run(self):
        started = self.clock()
        while not self.done.wait(POLL_SECONDS) and self.clock() - started < TEACH_SECONDS:
            self.poll()

    def poll(self):
        try:
            now = self.read()
        except (OSError, LookupError) as error:
            self.error = str(error)
            return
        with self.lock:
            for step in changes(self.before, now):
                last = self.steps[-1] if self.steps else None
                if last and step[0] == last[0] == "set_text" and step[1] == last[1]:
                    self.steps[-1] = step            # typing "h", "he", "hello" is one step
                elif step != last:
                    self.steps.append(step)
            self.before = now

    def stop(self):
        """Save what was shown as a routine; returns (name, commands). ValueError if nothing changed."""
        from chutku import routines
        self.done.set()
        if self.thread:
            self.thread.join(timeout=5)
        self.poll()
        commands = [routines.desktop_command(verb, self.app, name, text) for verb, name, text in self.steps]
        if not commands:
            raise ValueError("Nothing changed in that window, so there is nothing to save"
                             + (f" ({self.error})." if self.error else ". Try again, a little slower."))
        if len(commands) > routines.MAX_TAUGHT:
            raise ValueError(f"That was {len(commands)} steps; I can learn up to {routines.MAX_TAUGHT} at a time.")
        return routines.save_taught(self.name, commands), commands


def teaching():
    return _session["teacher"] is not None


def register_teach_tools(registry):
    from chutku.tools.registry import EMPTY_ARGUMENT_SCHEMA, Risk, Tool, ToolResult, Verification

    def start(arguments, _context):
        if teaching():
            return ToolResult({"error": "I am already watching; say 'ho gaya' first."}, Verification.FAIL)
        teacher = Teacher(arguments["app"], arguments["name"])
        try:
            teacher.start()
        except (OSError, LookupError) as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        _session["teacher"] = teacher
        return ToolResult({"watching": arguments["app"], "name": arguments["name"],
                           "summary": f"Dekh rahi hoon: {arguments['app']} mein ek baar karke dikhao, phir 'ho gaya' "
                                      "bolo. Password/PIN wale fields main record nahi karti."}, Verification.PASS)

    def stop(_arguments, _context):
        teacher, _session["teacher"] = _session["teacher"], None
        if teacher is None:
            return ToolResult({"error": "I was not watching anything."}, Verification.FAIL)
        try:
            name, commands = teacher.stop()
        except ValueError as error:
            return ToolResult({"error": str(error)}, Verification.FAIL)
        return ToolResult({"name": name, "commands": commands,
                           "summary": f"Seekh liya, '{name}': {'; '.join(commands)}. Bolo '{name}' to main dobara "
                                      "karungi (pehli baar saath mein dekhna)."}, Verification.PASS)

    registry.register(Tool("teach.start", "Teach mode: watch ONE open app window while the owner shows a task once; "
        "'ho gaya' saves it as a routine (name). Password/PIN fields are never recorded.", Risk.OBSERVATION, start,
        required_capability="screen.observe", argument_schema={"type": "object", "properties": {
            "app": {"type": "string", "minLength": 1, "maxLength": 120},
            "name": {"type": "string", "minLength": 1, "maxLength": 30, "pattern": "^[A-Za-z][A-Za-z0-9 -]*$"}},
            "required": ["app", "name"], "additionalProperties": False},
        prerequisites=("Windows; the app window open; agent-desktop installed (tools/)",),
        reversibility="not_applicable", success_predicate="teach_session_started"))
    registry.register(Tool("teach.stop", "End teach mode and save what the owner showed as a routine.",
        Risk.REVERSIBLE, stop, argument_schema=EMPTY_ARGUMENT_SCHEMA, reversibility="compensatable",
        success_predicate="routine_written_previous_version_returned"))

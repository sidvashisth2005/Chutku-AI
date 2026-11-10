"""Direct control requests from the phone: pointer, keys, text, window and monitor (PhoneControl, mixed into remote.server.PhoneHandler)."""
from __future__ import annotations

import time

from chutku.remote.auth import RemoteDenied


MONITOR_SECONDS = 2.0


class PhoneControl:
    """Methods of PhoneHandler, kept here to keep server.py short."""

    def _post_control_window(self, record, data):
        return self._control().focus(int(data.get("id")), self._monitor())

    def _post_control_read(self, record, data):
        """Read aloud: the paragraph of text under the finger (the phone speaks it), while the screen is shared."""
        screen = self.server.screen
        if not screen or screen["device"] != record["device"] or time.monotonic() > screen["until"]:
            raise RemoteDenied("Start screen view with your PIN.", 403)
        from chutku.remote import targets
        from chutku.remote.control import to_pixels
        x, y = to_pixels(self._monitor(), data.get("x"), data.get("y"))
        return {"text": targets.text_at(x, y)}

    def _control(self):
        control = self.server.control
        if control is None or not control.alive():
            raise RemoteDenied("Start control with your PIN first.", 409)
        return control

    def _monitor(self):
        if self.server.monitor is not None:
            return self.server.monitor
        seen = getattr(self.server, "monitor_seen", None)   # the latest frame's monitor: no capture per trackpad move
        if seen and time.monotonic() - seen[0] < MONITOR_SECONDS:
            return seen[1]
        from chutku.remote.control import primary_monitor
        rect = primary_monitor()
        self.server.monitor_seen = (time.monotonic(), rect)
        return rect

    def _post_control_input(self, record, data):
        events = data.get("events")
        if not isinstance(events, list):
            raise RemoteDenied("Send a list of events.", 400)
        return self._control().pointer(events, self._monitor())

    def _post_control_text(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:   # only sent when the laptop asked for it (a command window): always checked
            self._pin(record, data.get("pin"), strict=True)
            pin_ok = True
        return self._control().text(data.get("text", ""), enter=bool(data.get("enter")), pin_ok=pin_ok)

    def _post_control_keys(self, record, data):
        pin_ok = False
        if data.get("pin") is not None:
            self._pin(record, data.get("pin"), strict=True)
            pin_ok = True
        return self._control().keys(data.get("combo", ""), pin_ok=pin_ok)

    def _post_control_stop(self, record, data):
        if self.server.control is not None:
            self.server.control.end("stopped from the phone")
        self.server.control = None
        self.server._border(False)
        return {"control": False}

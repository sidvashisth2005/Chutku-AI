"""The laptop side of phone access (W6): turn it on or off, make a pairing code (and QR), arm or disarm control,
remove a phone. Used by the dashboard's Phone panel, the tray, the remote.* tools ("phone connect karo",
"remote band karo", "phone hatao") and the Ctrl+Alt+Shift+P kill hotkey.
"""
from __future__ import annotations

import threading

from chutku.remote import tailscale
from chutku.remote.auth import RemoteStore

PORT = 8766
_current = {"manager": None}


def current():
    return _current["manager"]


class RemoteManager:
    def __init__(self, core, *, port=PORT, runner=None, server_factory=None):
        self.core, self.port, self.runner = core, port, runner
        self.store = RemoteStore(core.base)
        self.server = None
        self.server_factory = server_factory
        _current["manager"] = self

    # -- state ----------------------------------------------------------------------------------------------------
    def status(self):
        settings = self.store.settings()
        return {**settings, "running": self.server is not None,
                "url": f"https://{settings['host']}/" if settings.get("host") else None,
                "phone_active": self.active(), "viewing": bool(self.server and self.server.viewing()),
                "controlling": bool(self.server and self.server.controlling())}

    def active(self):
        return bool(self.server is not None and self.store.active())

    # -- on / off -------------------------------------------------------------------------------------------------
    def enable(self):
        state = tailscale.status(runner=self.runner)
        if not state["installed"] or not state["logged_in"]:
            return {"enabled": False, "steps": state.get("steps") or tailscale.STEPS}
        if tailscale.funnel_exposes(self.port, runner=self.runner):
            return {"enabled": False, "steps": "Tailscale Funnel is on for this port. Turn Funnel off first; "
                                               "Chutku never runs on the public internet."}
        self.store.configure(host=state["host"], login=state["login"], enabled=True)
        self.start()
        if not tailscale.serve_on(self.port, runner=self.runner):
            self.disable()
            return {"enabled": False, "steps": "`tailscale serve` failed. Open Tailscale and try again."}
        return {"enabled": True, "url": f"https://{state['host']}/"}

    def start(self, for_relay=False):
        """Start the phone server (on Chutku's start-up too, when phone access was left on). for_relay: also without
        Tailscale, because the account relay's client is its only caller then (on loopback)."""
        if self.server is not None or not (for_relay or self.store.settings()["enabled"]):
            return self.server
        if self.server_factory is not None:
            self.server = self.server_factory(self.core, self.port)
        else:
            from chutku.remote.server import RemoteServer
            self.server = RemoteServer(self.core, self.port, store=self.store, tailscale_runner=self.runner)
            self.server.watch_funnel()
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.3}, name="chutku-phone",
                         daemon=True).start()
        return self.server

    def disable(self):
        tailscale.serve_off(runner=self.runner)
        self.store.configure(enabled=False, control_allowed=False)
        if self.server is not None:
            server, self.server = self.server, None
            server.end_all("phone access turned off")
            server.shutdown()
            server.server_close()
        return {"enabled": False}

    # -- pairing, control, devices --------------------------------------------------------------------------------
    def pair_code(self):
        settings = self.store.settings()
        if not settings["enabled"] or not settings["host"]:
            return {"error": "Turn phone access on first (\"phone connect karo\")."}
        code = self.store.new_pairing_code()
        link = f"https://{settings['host']}/#code={code}"
        return {"code": code, "link": link, "minutes": 10, "qr_svg": qr_svg(link)}

    def arm(self, on):
        """Direct control may be switched ON only here, at the laptop (never from the phone)."""
        if not on:
            return self.disarm("disarmed at the laptop")
        self.store.configure(control_allowed=True)
        return {"control_allowed": True}

    def disarm(self, reason="Ctrl+Alt+Shift+P"):
        if self.server is not None:
            self.server.disarm(reason)
        else:
            self.store.configure(control_allowed=False)
        return {"control_allowed": False}

    def revoke(self, device_id):
        self.store.revoke(device_id)
        return {"revoked": device_id}


def qr_svg(text):
    """An SVG QR code for the pairing link when the `qrcode` package is installed; None otherwise (the link and the
    8-character code are always shown too)."""
    try:
        import io
        import qrcode
        import qrcode.image.svg
        image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception:
        return None

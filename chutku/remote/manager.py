"""The laptop side of phone access (W6): turn it on or off, make a pairing code (and QR), arm or disarm control,
remove a phone. Used by the dashboard's Phone panel, the tray, the remote.* tools ("phone connect karo",
"remote band karo", "phone hatao") and the Ctrl+Alt+Shift+P kill hotkey.
"""
from __future__ import annotations

import re
import subprocess
import threading

from chutku.remote import tailscale
from chutku.remote.auth import RemoteStore

PORT = 8766
DOWNLOAD = "https://tailscale.com/download/windows"
PHONE_STEPS = ("On the phone: install the free Tailscale app (Play Store / App Store) and sign in with the same account "
               "as this laptop.",
               "Scan this code with the phone's camera (or open the link on the phone).",
               "Choose a 4-6 digit PIN. Done: the laptop's screen appears on the phone.")
_current = {"manager": None}


def current():
    return _current["manager"]


class RemoteManager:
    def __init__(self, core, *, port=PORT, runner=None, server_factory=None, launch=None, browse=None):
        self.core, self.port, self.runner = core, port, runner
        self.store = RemoteStore(core.base)
        self.server = None
        self.server_factory = server_factory
        self.launch, self.browse = launch or _launch, browse or _browse   # tests pass fakes
        self.installing, self.signing_in, self.sign_in_url = None, False, None
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
        threading.Thread(target=self._keep_awake, args=(self.server,), name="chutku-phone-awake", daemon=True).start()
        return self.server

    def _keep_awake(self, server, every=60.0, check=None):
        """Owner 2026-11-07: a sleeping laptop can't be reached. While phone access runs and the laptop is on mains
        power, Windows is asked not to sleep (the screen may still turn off and lock). SetThreadExecutionState holds
        only for the thread that set it, so this one thread owns it and releases it when phone access stops."""
        from chutku.nightshift import keep_awake, on_ac_power
        check = check or on_ac_power
        try:
            while self.server is server and not server.stopped.is_set():
                keep_awake(check() is not False)   # None (a desktop that won't say) counts as mains
                server.stopped.wait(every)
        finally:
            keep_awake(False)

    def disable(self):
        tailscale.serve_off(runner=self.runner)
        self.store.configure(enabled=False, control_allowed=False)
        if self.server is not None:
            server, self.server = self.server, None
            server.end_all("phone access turned off")
            server.shutdown()
            server.server_close()
        return {"enabled": False}

    # -- one button (owner 2026-11-08: "a cakewalk from download to use, no brainstorming") -------------------------
    def connect(self):
        """Whatever is still missing for the phone, in order: install Tailscale (winget, one Windows prompt), sign in
        (the browser opens), turn phone access on, then the pairing QR code. The page calls it again every few seconds
        until it answers "ready"; each call only checks and moves on, so it is safe to press again."""
        state = tailscale.status(runner=self.runner)
        if not state["installed"]:
            return self._install_tailscale()
        self.installing = None
        if not state["logged_in"]:
            return self._sign_in()
        self.signing_in = False
        if not self.store.settings()["enabled"] or self.server is None:
            result = self.enable()
            if not result.get("enabled"):
                return {"stage": "problem", "message": result.get("steps") or "Phone access could not start."}
        pairing = self.pair_code()
        if pairing.get("error"):
            return {"stage": "problem", "message": pairing["error"]}
        return {"stage": "ready", **pairing, "phone_steps": list(PHONE_STEPS)}

    def _install_tailscale(self):
        job = self.installing
        if job is not None and job.poll() not in (None, 0):   # winget failed: say so, and try again on the next press
            self.installing = None
            return {"stage": "problem", "message": f"Tailscale could not be installed here. Install it from {DOWNLOAD}, "
                                                   "then press Connect again.", "url": DOWNLOAD}
        if job is None:
            try:
                self.installing = self.launch(["winget", "install", "--id", "Tailscale.Tailscale", "--exact", "--silent",
                                               "--accept-package-agreements", "--accept-source-agreements"])
            except OSError:   # no winget on this Windows
                return {"stage": "problem", "message": f"Install Tailscale from {DOWNLOAD}, then press Connect again.",
                        "url": DOWNLOAD}
        return {"stage": "installing", "message": "Installing Tailscale (free, about a minute). If Windows asks, press "
                                                  "Yes."}

    def _sign_in(self):
        if not self.signing_in:
            self.signing_in = True
            threading.Thread(target=self._log_in, name="chutku-tailscale-login", daemon=True).start()
        return {"stage": "sign_in", "url": self.sign_in_url,
                "message": "Sign in to Tailscale in the browser window that opened (a Google account is fine). Use the "
                           "same account on your phone."}

    def _log_in(self):
        """`tailscale login` prints the sign-in address and waits; open it in the browser for the owner."""
        exe = tailscale.executable()
        if exe is None:
            self.signing_in = False
            return
        try:
            job = self.launch([exe, "login"], output=True)
            for line in job.stdout:
                found = re.search(r"https://login\.tailscale\.com/\S+", line)
                if found and self.sign_in_url != found.group(0):
                    self.sign_in_url = found.group(0)
                    self.browse(self.sign_in_url)
            job.wait()
        except OSError:
            pass
        finally:
            self.signing_in = False

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


def _launch(args, output=False):
    return subprocess.Popen(args, stdout=subprocess.PIPE if output else subprocess.DEVNULL,
                            stderr=subprocess.STDOUT if output else subprocess.DEVNULL, text=output,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _browse(url):
    import webbrowser
    webbrowser.open(url)

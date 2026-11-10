"""Dashboard presence: the HUD, the presence bar, the tray, the window and the phone server (DashboardPresence)."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import threading
import time

from chutku.app import PROJECT_ROOT
from chutku.core.action_control import ActionControl
from chutku.dashboard_helpers import _log, open_app_window


class DashboardPresence:
    """Methods of DashboardServer, kept here to keep dashboard.py short."""

    def hud_video(self):
        """X13: the YouTube video playing in Chutku's own window (youtube.play_here), for at most 4 hours."""
        from chutku.tools.internet import hud_video_file
        try:
            video = json.loads(hud_video_file(self.base).read_text(encoding="utf-8"))
            if time.time() - float(video["at"]) < 4 * 3600 and re.fullmatch(r"[\w-]{11}", video["id"]):
                return {"id": video["id"], "title": str(video.get("title", ""))[:150]}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    # -- W6: phone access ---------------------------------------------------------------------------------------
    def start_remote(self):
        """Phone access (when the owner left it on): only the real install, never tests or demos."""
        if Path(self.base).resolve() != Path(PROJECT_ROOT).resolve():
            return None
        from chutku.remote.manager import RemoteManager
        self.remote = RemoteManager(self)
        try:
            self.remote.start()
        except OSError:
            _log().exception("the phone server could not start")
        try:   # the phone app through the account relay (set up by chutku.cli setup)
            from chutku.relay import client
            self.relay = client.start(self)
        except Exception:
            _log().exception("the account relay could not start")   # Chutku keeps running without the phone app
        return self.remote

    def phone_active(self):
        return bool(self.remote is not None and self.remote.active())

    def remote_kill(self):
        """Ctrl+Alt+Shift+P: end phone control now and forbid it until it is armed again at the laptop."""
        from chutku.voice.handsfree import chime
        if self.remote is not None:
            self.remote.disarm("Ctrl+Alt+Shift+P")
        chime("busy")
        self.hud_state["message"] = "Phone control stopped (Ctrl+Alt+Shift+P)."

    # -- HUD ---------------------------------------------------------------------------
    def _hud_show(self):
        if self.hud is not None:
            self.hud.show()

    def _hud_set(self, phase, *, transcript=None, message=None, session_id=None):
        self.hud_state = {"phase": phase, "transcript": transcript, "message": message, "session_id": session_id}
        self._hud_show()

    def hud_status(self):
        from chutku.voice.recognition import LEVEL
        state = dict(self.hud_state)
        session = None
        if state.get("session_id"):
            try:
                session = self.agent_sessions.get(state["session_id"]).snapshot()
            except (KeyError, ValueError):
                session = None
        if session is not None:
            state["phase"] = {"planning": "thinking", "running": "running", "waiting_confirmation": "confirm",
                              "done": "done", "clarify": "clarify", "queued": "thinking"}.get(session["status"], "error")
        state["session"] = session
        if session is not None and session.get("suspicious"):
            state["message"] = "⚠ What I read tried to give me instructions: every change waits for your OK."
        state["level"] = LEVEL["rms"] if time.monotonic() - LEVEL["at"] < 0.3 else 0.0
        state["paused"] = ActionControl(self.base).paused
        from chutku.voice import mic
        state["mic_muted"] = mic.muted()
        live = self.live
        if live is not None and live.active.is_set():
            state["conversation"] = list(live.transcript)
            state["live_model"] = live.model
            if session is None or session["status"] in {"done", "clarify", "failed", "stopped", "cancelled"}:
                state["phase"] = "listening"  # the conversation goes on after a task
        return state

    @classmethod
    def presence_mood(cls, phase, steps, heard=""):
        """X11/Y1: the face's mood. Happy only when the task is done and every completed step was verified; hearts
        when the owner thanks her; angry brows while she works on something he said in annoyance."""
        if phase in {"paused", "error", "confirm"}:
            return cls.MOODS[phase]
        from chutku.translit import roman
        said = roman(heard or "")
        if cls.LOVE.search(said):
            return "love"
        if cls.ANNOYED.search(said) and phase in {"listening", "thinking", "running", "speaking"}:
            return "annoyed"
        if phase == "done":
            completed = [s for s in steps if s.get("state") == "COMPLETED"]
            failed = any(s.get("state") in {"FAILED", "DENIED"} for s in steps)
            return "happy" if completed and not failed and all(s.get("verified") for s in completed) else "calm"
        return cls.MOODS.get(phase, "calm")

    def presence_state(self):
        """What the presence orb shows (W4): its phase, voice levels in and out, captions and the live task."""
        from chutku.voice import tts
        from chutku.voice.session import voice_session
        state = self.hud_status()
        speaking = voice_session.snapshot().state == "speaking"
        phase = state.get("phase", "idle")
        if speaking:
            phase = "speaking"
        if state.get("paused") and phase in {"idle", "done", "error"}:
            phase = "paused"
        session = state.get("session") or {}
        steps = [{"tool": s.get("tool"), "purpose": str(s.get("purpose") or "")[:90], "state": s.get("state"),
                  "verified": s.get("verification") == "PASS"} for s in (session.get("steps") or [])][-8:]
        phase = phase if phase in self.PHASES else "idle"
        return {"phase": phase, "mood": self.presence_mood(phase, steps, state.get("transcript")),
                "mic_level": round(float(state.get("level") or 0.0), 4),
                "voice_level": round(tts.speaking_level(), 3) if speaking else 0.0,
                "heard": state.get("transcript") or "", "message": state.get("message") or "",
                "reply": str(session.get("reply") or "")[:400], "goal": str(session.get("goal") or "")[:160],
                "session_id": session.get("id"), "status": session.get("status"), "steps": steps,
                "pending": (session.get("pending") or {}).get("approval") if session.get("status") == "waiting_confirmation" else None,
                "paused": bool(state.get("paused")), "mic_muted": bool(state.get("mic_muted")),
                "video": self.hud_video(),
                "conversation": [list(t) for t in (state.get("conversation") or [])][-4:],
                "healed": bool(self.healed), "phone": self.phone_active(),
                "phone_viewing": bool(self.remote and self.remote.server and self.remote.server.viewing()),
                "phone_control": bool(self.remote and self.remote.server and self.remote.server.controlling())}

    def hud_submit(self, text):
        mode = self.preferences.load()["handsfree_mode"]
        self._hud_set("thinking", transcript=text)
        session = self.begin_session(text, mode, "text")
        self.hud_state["session_id"] = session.id

    def start_tray(self):
        """Tray icon with the same controls as the dashboard header buttons."""
        from chutku.tray import Tray
        control = ActionControl(self.base)

        def toggle():
            control.resume() if control.paused else control.pause()

        def stop():   # "Quit Chutku": every process ends, cleanly (no pause on the next start), 2026-11-01
            if self.heartbeat is not None:
                control.quit()
        def restart():   # WA6: quit cleanly and start again (never leaves actions paused)
            if self.heartbeat is not None:
                from chutku import restart as restarting
                restarting.request(self.base)
        self.tray = Tray(open_dashboard=lambda: open_app_window(self.url), toggle_pause=toggle, stop=stop,
                         restart=restart,
                         is_paused=lambda: control.paused, guard_active=lambda: self.heartbeat is not None,
                         show_window=self.show_window)
        self.tray.start()
        self.tray.ready.wait(5)
        return self.tray.error

    def start_presence(self):
        """W4: the presence orb window (pywebview) as a child process of this core, so it closes with Chutku.
        False when it is off, not installed, or this is not the real install (then the Tk HUD is used)."""
        if Path(self.base).resolve() != Path(PROJECT_ROOT).resolve():
            return False
        if not self.preferences.load().get("presence_overlay", True):
            return False
        from chutku import presence
        if not presence.available():
            return False
        import subprocess
        import sys
        try:
            from chutku.core.paths import CODE_ROOT   # W2: -m finds chutku from the code folder, not the data
            self.presence_process = subprocess.Popen([sys.executable, "-m", "chutku.presence", self.url],
                                                     cwd=str(CODE_ROOT),
                                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError:
            _log().exception("the presence window could not start; using the HUD")
            return False
        self.watch_presence()
        return True

    def show_window(self):
        """Tray "Show Chutku window": the orb if it runs (restarted when it was closed), else the panel."""
        process = getattr(self, "presence_process", None)
        if process is not None and process.poll() is None:
            from chutku.presence import bring_to_front
            bring_to_front()
        elif not self.start_presence():
            if self.hud is None:
                self.start_hud()
            self._hud_show()

    def watch_presence(self, wait=8.0):
        """2026-11-01: the orb sometimes never appeared and nothing said why. If its process dies or no window
        shows within `wait` seconds, the Tk panel starts instead (and the reason is logged)."""
        def run():
            from chutku.presence import window_exists
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if self.presence_process.poll() is not None:
                    break
                if window_exists():
                    return
                time.sleep(0.5)
            _log().warning("the presence window did not appear (exit code %s); using the HUD",
                           self.presence_process.poll())
            if self.hud is None:
                self.start_hud()
        threading.Thread(target=run, name="chutku-presence-watch", daemon=True).start()

    def start_hud(self):
        from chutku.hud import Hud
        server = self

        class Actions:
            confirm = staticmethod(lambda session_id, approve: server.confirm_session(session_id, approve))
            stop = staticmethod(lambda session_id: server.stop_session(session_id))
            submit = staticmethod(lambda text: server.hud_submit(text))
            listen = staticmethod(lambda: server.handsfree_request())
            mute = staticmethod(lambda: server.toggle_mute())
            resume = staticmethod(lambda: ActionControl(server.base).resume())
        self.hud = Hud(self.hud_status, Actions)
        self.hud.start()
        self.hud.ready.wait(5)
        return self.hud.error

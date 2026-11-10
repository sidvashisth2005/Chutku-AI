"""Dashboard voice: hands-free requests, voice approvals, Gemini Live, the screen copilot (DashboardVoice)."""
from __future__ import annotations

import threading
import time

from chutku.core.action_control import ActionControl
from chutku.core.execution_lock import ExecutionBusy
from chutku.dashboard_helpers import _log, paused_explanation, paused_spoken


class DashboardVoice:
    """Methods of DashboardServer, kept here to keep dashboard.py short."""

    def _approve_by_voice(self, session, snapshot):
        """Ask the pending step aloud, listen for haan/nahi, apply it. False when no clear answer was heard."""
        from chutku.voice.approval import decide, spoken_question
        from chutku.voice.handsfree import chime
        question = spoken_question((snapshot.get("pending") or {}).get("approval") or {})
        for attempt in range(2):
            self._hud_set("confirm", message=question)
            self._speak(question if attempt == 0 else "Sorry, haan ya na?")
            chime("listen")
            heard = self._listen_once()
            answer = decide(heard)
            if session.snapshot()["status"] != "waiting_confirmation":
                return True  # answered on screen meanwhile
            if answer is None:
                continue
            try:
                self.confirm_session(session.id, answer)
            except (ValueError, ExecutionBusy):
                return True  # already decided elsewhere
            if not answer:
                self._speak("Theek hai, cancel kar diya.")
            self.hud_state["transcript"] = heard
            time.sleep(0.5)
            return True
        self._speak("I didn't catch a clear haan or na. The button is on the screen.")
        return False

    def handsfree_request(self, command=None, source="hotkey"):
        """Hotkey or wake phrase. With conversation mode on (and Gemini enabled) this starts, or with the
        hotkey ends, a live voice conversation; otherwise: remember the screen, show the HUD, listen once
        (unless the command was already said), run."""
        from chutku import vision
        from chutku.voice.handsfree import chime
        live = self.live
        if live is not None and live.active.is_set():
            # Only the hotkey ends a conversation. A wake-phrase match while talking is ignored: it was the
            # wake listener catching noise or Chutku's own voice (it used to end conversations at random).
            if command is None and source == "hotkey":
                live.stop()
                self._hud_set("done", message="Conversation ended.")
            return
        if ActionControl(self.base).paused:
            self._paused_voice(source, command)   # always answer out loud; the hotkey may lift the pause by voice
            return
        if source == "hotkey" and command is None:
            self._barge_in()
        conversation = self.preferences.load().get("conversation", True)
        from chutku.voice import mic
        mic.set_muted(False)   # calling Chutku means "listen to me now"
        if conversation and self.start_live(command):
            return
        if conversation and getattr(self, "live_error", None) and self.voice_replies:
            # 2026-10-31: Gemini Live silently failed (key rejected) and the owner only noticed "the voice changed".
            self._speak(f"{self.live_error}, isliye abhi local mode mein sun rahi hoon.")
        if self.action_lock.locked() and not command:
            self._hud_show()  # show what is running now
            chime("busy")
            return
        vision.remember_moment()  # "this" = what was on screen the instant you called Chutku
        mode = self.preferences.load()["handsfree_mode"]
        try:
            if command:
                if source == "wake":
                    chime("listen")   # every wake is heard and seen, so a false wake never goes unnoticed
                self._hud_set("thinking", transcript=command)
                session = self.begin_session(command, mode, "voice")
                if session.status == "queued":  # runs after the current order; its answer is spoken then
                    self._hud_set("thinking", transcript=command,
                                  message=f"Queued: starts after the current task ({len(self.queued_ids())} waiting).")
                    chime("listen")
                    return
            else:
                self._hud_set("listening")
                chime("listen")
                session, transcript, message = self.voice_request(mode)
                if session is None:
                    self._hud_set("error", message=message or "I didn't catch that.")
                    chime("busy")
                    # 2026-10-30 00:50: the owner's hotkey request came out as "Kholo." (unclear) and got only a
                    # beep; a minute later the emergency stop was pressed. Always say what happened.
                    if self.voice_replies:
                        self._speak("Sorry, theek se sunai nahi diya. Ctrl+Alt+Space dabake thoda paas se phir bolo.")
                    return
                self.hud_state["transcript"] = transcript
            self.hud_state["session_id"] = session.id
            self._wait_for(session)
            follow_up = float(self.preferences.load().get("follow_up_seconds", 0) or 0)
            if follow_up > 0 and session.snapshot()["status"] in {"done", "clarify"}:
                # W3: after her answer she keeps listening a few seconds; just speak, no hotkey or wake phrase.
                self._local_conversation(mode, wait_seconds=follow_up)
        except ExecutionBusy:
            chime("busy")

    def _paused_voice(self, source, command=None):
        """Called while actions are paused. Before 2026-10-29 the hotkey only beeped and the wake phrase failed
        silently, so the owner never learned why Chutku "did nothing" for three days. Now she says why. After
        the hotkey (a key pressed at this PC, so the owner) a spoken "resume" lifts the pause; nothing else heard
        here runs. A wake phrase only gets the explanation: a voice in the room may not lift a pause."""
        from chutku import control_intent
        from chutku.voice.handsfree import chime
        why = paused_spoken(self.base)
        self._hud_set("error", message=paused_explanation(self.base, short=True))
        if source != "hotkey":
            self._say(why + " Chalu karne ke liye Ctrl+Alt+Space dabake resume bolo.")
            return
        if self.action_lock.locked():
            chime("busy")
            return
        heard = command
        if not heard:
            self._say(why + " Chalu karna hai to resume bolo.")
            chime("listen")
            self._hud_set("listening", message="Paused. Say \"resume\" to switch actions back on.")
            heard = self._listen_paused()
        if heard and control_intent.heard_resume(heard):
            try:
                ActionControl(self.base).resume()
            except ExecutionBusy:
                self._say("Abhi ek kaam chal raha hai, thodi der mein phir se bolo.")
                return
            self._hud_set("done", transcript=heard, message="Resumed: actions are on again.")
            self._say("Chalu ho gayi. Ab bolo, kya karna hai?")
            return
        self._hud_set("error", transcript=heard or None, message=paused_explanation(self.base, short=True))

    def _listen_paused(self):
        """One transcript while paused (the listen tool refuses to run then). Used only to hear "resume"."""
        from chutku.voice import recognition
        from chutku.voice.session import voice_session
        wake = self.wake
        if wake is not None:
            wake.busy.set()

        class Unpaused:
            @staticmethod
            def check():
                return None
        try:
            with voice_session.active("listening"):
                heard = recognition.transcribe(recognition.capture(Unpaused()))
        except Exception:
            _log().exception("listening while paused failed")
            return ""
        finally:
            if wake is not None and not getattr(wake, "handling", False):
                wake.busy.clear()
        text = heard.get("text", "") if isinstance(heard.get("text"), str) else ""
        # One short word scores lower than a sentence; only "resume" is acted on here, so a lower bar is safe.
        return text.strip() if heard.get("confidence", 0) >= 0.2 else ""

    def screen_copilot(self, question=None):
        """Ctrl+Alt+S (W5): keep what is on screen right now, listen ~4 s for a question ("ye error kya hai?"),
        then answer it out loud from the screen copilot. No question: "what is on my screen, anything to fix?"."""
        from chutku import vision
        from chutku.voice.handsfree import chime
        from chutku.quick_intents import SCREEN_COPILOT
        vision.remember_moment()          # before the HUD or anything else appears on screen
        if ActionControl(self.base).paused:
            self._paused_voice("hotkey", None)
            return None
        self._barge_in()
        if question is None:
            self._hud_set("listening", message="Screen ke baare mein kya poochna hai? (ya chup raho: main bata dungi)")
            chime("listen")
            question = self._listen_once(4)
        question = (question or "").strip()
        if question and SCREEN_COPILOT.search(question):
            goal = question
        else:
            goal = ("screen dekh ke batao: " + question) if question else "screen dekh ke batao kya hai, kuch fix karna hai?"
        mode = self.preferences.load()["handsfree_mode"]
        try:
            session = self.begin_session(goal, mode, "voice", speaker_check=False)
        except ExecutionBusy:
            chime("busy")
            return None
        self.hud_state["session_id"] = session.id
        return session

    def _barge_in(self, settle=1.0):
        """Hotkey while she is talking: stop her now (and drop the rest of that answer), then listen (W3)."""
        from chutku.voice import tts
        from chutku.voice.session import voice_session
        if voice_session.snapshot().state != "speaking":
            return False
        tts.stop()
        deadline = time.monotonic() + settle
        while voice_session.snapshot().state == "speaking" and time.monotonic() < deadline:
            time.sleep(0.05)
        return True

    def _local_conversation(self, mode, turns=6, wait_seconds=None):
        """Offline conversation: after each spoken answer Chutku listens again (no wake phrase needed) until
        silence, noise, or "bas" / "bye". Everything runs on this PC: Whisper, the local model, Windows' voice."""
        from chutku.voice.handsfree import chime
        from chutku.voice.heard import meaningful
        from chutku.voice.session import voice_session
        for _turn in range(turns):
            deadline = time.monotonic() + 90
            while (self.action_lock.locked() or voice_session.quiet_for() < 0.5) and time.monotonic() < deadline:
                time.sleep(0.1)   # let the answer finish speaking: the mic must not hear Chutku itself
            from chutku.voice import mic
            waited = time.monotonic()
            while mic.muted() and wait_seconds is None and time.monotonic() - waited < 60:
                time.sleep(0.2)   # muted: wait for Ctrl+Alt+M instead of listening to the room
            if mic.muted():
                mic.set_muted(False)
                self._hud_set("done", message="Conversation ended.")
                return
            self._hud_set("listening", message="Anything else? (say \"bas\" to stop)")
            chime("listen")
            heard = self._listen_once(wait_seconds)
            if not heard or not meaningful(heard) or self.END_CONVERSATION.fullmatch(heard):
                self._hud_set("done", message="Conversation ended.")
                return
            try:
                session = self.begin_session(heard, mode, "voice")
            except ExecutionBusy:
                return
            self.hud_state.update({"transcript": heard, "session_id": session.id})
            self._wait_for(session)

    # -- live conversation ----------------------------------------------------------------
    def start_live(self, opening=None):
        """Start a live conversation; False when it cannot (no Gemini, offline), so the caller falls back."""
        from chutku import vision
        from chutku.tools.builder import gemini_allowed
        from chutku.voice.handsfree import chime
        from chutku.voice.live import LiveConversation
        key = gemini_allowed(self.base)
        self.live_error = None
        if not key:
            self.live_error = "Gemini ki key ya permission set nahi hai"
            return False
        from chutku.online import reachable
        if not reachable():
            self.live_error = "internet nahi mil raha"
            return False   # offline: the local conversation takes over at once (no 12 s connection wait)
        vision.remember_moment()
        if self.wake is not None:
            self.wake.busy.set()  # one microphone owner at a time
            self.wake.hold.set()  # ...for the whole conversation (busy alone was cleared as soon as this returned)
        live = LiveConversation(self, key)
        live.topic = opening or ""   # the voice model's memory slice is picked for this topic
        self.live = live
        self._hud_set("listening", message="Connecting…")
        if not opening:
            # Z4: "speak now" at once; the conversation records from here and sends it when connected (~1.3 s).
            chime("listen")
        live.start()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and live.model is None and not live.closed.is_set():
            time.sleep(0.1)
        if live.model is None:
            self.live_error = "Gemini se connect nahi ho paayi (key reject ho rahi hai ya model band hai)"
            live.stop()
            if self.wake is not None:
                self.wake.hold.clear()
                self.wake.busy.clear()
            self.live = None
            return False
        if opening:
            chime("listen")
            live.trust_opening(opening)  # said right after the wake phrase: heard clearly by the wake listener
            live.inject(opening)
        threading.Thread(target=self._after_live, args=(live,), daemon=True).start()
        return True

    def _after_live(self, live):
        live.closed.wait()
        from chutku.voice import mic
        mic.set_muted(False)   # mute lasts only for this conversation
        from chutku import recall
        recall.log_voice(live.full_transcript, base=self.base, tasked=getattr(live, "tasked_turns", None))
        if self.wake is not None:
            self.wake.hold.clear()
            self.wake.busy.clear()
        if self.live is live:
            self._hud_set("done", message=live.error or "Conversation ended.")

    def live_event(self, kind, **details):
        if kind == "connected":
            self.hud_state = {"phase": "listening", "transcript": None, "message": None,
                              "session_id": self.hud_state.get("session_id")}
            self._hud_show()

    def live_task(self, goal):
        """A task the conversation asked for: the normal agent path, narrated by the conversation."""
        mode = self.preferences.load()["handsfree_mode"]
        session = self.begin_session(goal, mode, "voice", silent=True, voice_source="live")
        self.hud_state["session_id"] = session.id
        return session

    def toggle_mute(self):
        """Ctrl+Alt+M / the HUD mic button: mute or unmute the microphone without stopping anything."""
        from chutku.voice import mic
        from chutku.voice.handsfree import chime
        now = mic.toggle()
        key = getattr(self.hotkey, "mute_hotkey", None) or "the mic button"
        self.hud_state["message"] = (f"Mic muted: I keep talking but don't hear the room. {key} to unmute."
                                     if now else "Mic on.")
        self._hud_show()
        chime("busy" if now else "listen")
        return now

    def start_handsfree(self):
        from chutku.voice.handsfree import HotkeyListener
        self.hotkey = HotkeyListener(lambda: self.handsfree_request(), on_mute=self.toggle_mute,
                                     on_screen=self.screen_copilot, on_kill=self.remote_kill)
        self.hotkey.start()
        self.hotkey.registered.wait(2)
        prefs = self.preferences.load()
        self.apply_wake(prefs["wake_word"])
        if prefs["wake_word"] or prefs.get("offline_mode"):
            self._preload_whisper()

    def _preload_whisper(self, delay=10.0):
        """Load offline speech recognition in the background once Chutku is up, so the first spoken command does
        not wait for the model (and its hash check). Only when the offline voice path is in use."""
        def work():
            time.sleep(delay)
            try:
                from chutku.voice import whisper_stt
                whisper_stt._load(self.base)
            except Exception:
                _log().warning("preloading Whisper failed", exc_info=True)   # the first transcription retries
        threading.Thread(target=work, name="chutku-whisper-preload", daemon=True).start()

    def apply_wake(self, enabled):
        from chutku.voice.handsfree import WAKE_PROMPT, WakeListener
        if enabled and (self.wake is None or not self.wake.is_alive()):
            from chutku.voice.whisper_stt import transcribe_pcm
            self.wake = WakeListener(lambda command: self.handsfree_request(command or None, source="wake"),
                                     lambda pcm: transcribe_pcm(pcm, language="en", base=self.base,
                                                                prompt=WAKE_PROMPT), base=self.base)
            self.wake.start()
        elif not enabled and self.wake is not None:
            self.wake.stop()
            self.wake = None

    def handsfree_status(self):
        prefs = self.preferences.load()
        wake = self.wake
        return {"hotkey": "Ctrl+Alt+Space", "hotkey_active": bool(self.hotkey and self.hotkey.registered.is_set()),
                "handsfree_mode": prefs["handsfree_mode"], "wake_word": prefs["wake_word"], "browser": prefs["browser"],
                "offline_mode": prefs.get("offline_mode", False), "brain": prefs.get("brain", "cloud_first"),
                "mic_muted": __import__("chutku.voice.mic", fromlist=["muted"]).muted(),
                "mute_hotkey": getattr(self.hotkey, "mute_hotkey", None) if self.hotkey else None,
                "wake_listening": bool(wake and wake.is_alive()), "wake_error": wake.error if wake else None,
                "wake_audio": {key: getattr(wake, key, 0) for key in ("overflows", "dropped", "restarts")} if wake else None,
                "wake_engine": getattr(wake, "engine", None) if wake else None,
                "wake_best_score": round(getattr(getattr(wake, "detector", None), "best_score", 0.0), 3) if wake else None,
                "latest_session": self.latest_session_id}

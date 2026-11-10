"""DashboardServer/DashboardHandler: the local web app on 127.0.0.1, speech queue, voice timings."""
from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import urlsplit, parse_qs

from chutku.app import PROJECT_ROOT, create_runtime
from chutku.agent_execution import AgentExecutionStore
from chutku.agent_loop import AgentSession, AgentSessionStore, RuntimeRouter, default_context
from chutku.policy.kernel import AutonomyMode
from chutku.core.action_control import ActionControl
from chutku.core.approvals import ApprovalStore
from chutku.core import progress
from chutku.core.execution_lock import ExecutionBusy
from chutku.presentation import present
from chutku.planning import execute_request
from chutku.tools.assistant import capabilities, LIMITS
from chutku.workflows import project_plan, preflight, run_project
from chutku.dashboard_helpers import (  # noqa: F401  (moved; still importable from here)
    _STOP_REASONS,
    _last_task_file,
    _log,
    _when,
    interrupted_task,
    open_app_window,
    paused_explanation,
    paused_spoken,
)
from chutku.dashboard_voice import DashboardVoice  # noqa: F401  (moved; still importable from here)
from chutku.dashboard_presence import DashboardPresence  # noqa: F401  (moved; still importable from here)
from chutku.dashboard_work import DashboardWork, MAX_QUEUED  # noqa: F401  (moved; still importable from here)


class PreviewStore:
    def __init__(self, ttl: float = 120):
        self.ttl = ttl
        self.pending: dict[str, tuple[float, dict]] = {}

    def add(self, plan: dict) -> str:
        now = time.monotonic()
        self.pending = {key: value for key, value in self.pending.items() if value[0] > now}
        if len(self.pending) >= 20:
            raise ValueError("Too many pending previews. Cancel a preview or wait two minutes.")
        token = secrets.token_urlsafe(24)
        self.pending[token] = (now + self.ttl, deepcopy(plan))
        return token

    def take(self, token: str) -> dict:
        item = self.pending.pop(token, None)
        if item is None or item[0] <= time.monotonic():
            raise ValueError("Preview expired, was cancelled or has already run. Preview the project again.")
        return item[1]

    def cancel(self, token: str) -> None:
        self.pending.pop(token, None)


class SpeechQueue:
    """Speaks sentences in order on one thread (with its own runtime) while the answer is still being written.

    W3: an interruption (hotkey barge-in, "ruko") drops whatever was still queued, and the first sentence records
    how long the owner waited from the end of their speech to Chutku's first sound (data/voice-timings.jsonl)."""

    def __init__(self, base, goal=""):
        import queue as _queue
        from chutku.voice import tts
        self.base, self.items, self.thread, self.spoken = base, _queue.Queue(), None, 0
        self.goal, self.stops, self.timed = goal, tts.STOPS["count"], False

    IDLE_SECONDS = 120

    def say(self, text):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, name="chutku-speech", daemon=True)
            self.thread.start()
        self.items.put(text)

    def _run(self):
        import queue as _queue
        with create_runtime(self.base) as runtime:
            while True:
                try:
                    text = self.items.get(timeout=self.IDLE_SECONDS)
                except _queue.Empty:
                    return   # nothing more to say (e.g. close() ran before an approved step spoke): free the runtime
                if text is None:
                    return
                from chutku.voice import tts
                if tts.STOPS["count"] != self.stops:
                    continue   # the owner interrupted: the rest of this answer is not spoken
                try:
                    started = time.monotonic()
                    result = runtime.run("voice.speak", {"text": text[:1000]}, provenance="tool_observed")
                    if not self.timed and text != FILLER:   # the real answer's first sound, not the filler
                        self.timed = True
                        record_voice_timing(self.base, self.goal, started, result)
                    self.spoken += 1
                except Exception:
                    _log().exception("speaking a sentence failed")

    def close(self, timeout=60):
        if self.thread is not None:
            self.items.put(None)
            self.thread.join(timeout)


FILLER = "Ek second."


def record_voice_timing(base, goal, speak_started, result):
    """End of the owner's speech -> Chutku's first sound, for a spoken answer (W3 target: instant 1.2 s, cloud
    2.5 s). Local file only; nothing about the audio is kept."""
    from chutku.voice.recognition import LAST_END
    ended = LAST_END.get("at")
    if ended is None or not isinstance(result, dict) or speak_started - ended > 120:
        return None
    output = result.get("output") or {}
    first = output.get("first_audio_s")
    latency = round(speak_started + (first if isinstance(first, (int, float)) else 0.0) - ended, 2)
    row = {"at": time.time(), "goal": str(goal)[:80], "seconds_to_first_audio": latency,
           "engine": output.get("engine")}
    try:
        path = Path(base) / "data" / "voice-timings.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    LAST_END["at"] = None   # one timing per heard request
    return latency


def speak_result(session, router):
    """Voice requests get a spoken answer (Chutku's own words, never an instruction)."""
    snapshot = session.snapshot()
    if session.origin != "voice" or snapshot["status"] == "waiting_confirmation" or getattr(session, "silent", False):
        return  # (live conversation tasks are narrated by the conversation itself)
    streamed = getattr(session, "streamed", None)
    if streamed is not None and streamed.spoken and snapshot["status"] == "done":
        return  # already spoken sentence by sentence while it was written
    import re
    text = re.sub(r"\s*\[Verified:.*\]\s*$", "", snapshot["reply"]).strip() or "Done."
    if any(step.get("low_trust") for step in snapshot["steps"]):   # this kind of step has been failing lately
        text = "Shayad ho gaya, ek baar check kar lo. " + text
    try:
        started = time.monotonic()
        result = router.default.run("voice.speak", {"text": text[:1000]}, provenance="tool_observed")
        record_voice_timing(router.default.granted_root.parent, snapshot["goal"], started, result)
    except Exception:
        _log().exception("spoken answer failed")  # the answer is still shown on screen


class DashboardServer(DashboardWork, DashboardPresence, DashboardVoice, ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, base: Path = PROJECT_ROOT, port: int = 8765, heartbeat=None):
        self.base = base
        self.token = secrets.token_urlsafe(32)
        self.previews = PreviewStore()
        self.sequence_previews = PreviewStore()
        self.approvals = ApprovalStore()
        self.brain_previews = PreviewStore(ttl=300)
        self.voice_previews = PreviewStore(ttl=120)
        self.agent_executions = AgentExecutionStore(ttl=600)
        self.agent_sessions = AgentSessionStore()
        from chutku.core.preferences import Preferences
        self.preferences = Preferences(base)
        self.latest_session_id = None
        self.hotkey = None
        self.wake = None
        self.hud = None
        self.live = None
        self.hud_state = {"phase": "idle", "transcript": None, "message": None, "session_id": None}
        self.planner_factory = None  # tests may inject (planner, fallback)
        self.action_lock = threading.Lock()
        self.heartbeat = heartbeat
        self.loop_tick = awake_clock()
        self.closing = threading.Event()
        self.healed = None             # the guard pause this core lifted after a restart (shown on the HUD)
        self.remote = None             # W6 phone access (chutku/remote/manager.py), real install only
        self.relay = None              # the phone app through the account relay (chutku/relay/client.py)
        # Fixed spoken replies (control answers, read-backs): only the real install speaks; tests turn it on with fakes.
        self.voice_replies = Path(base).resolve() == Path(PROJECT_ROOT).resolve()
        self.action_started = None
        self.work_queue = []           # orders given while another runs: (session, action), oldest first
        self.queue_lock = threading.Lock()
        self.batch = []                # sessions of the current back-to-back run, for the summary
        self.parallel_running = 0      # side-by-side tasks now running (Y3, at most MAX_PARALLEL)
        self.main_session = None       # the order holding the action lock (H18 steer target)
        self.board = None              # H15 research dispatcher (chutku/board.py), real install only
        self.downloads = None          # W5 offline pack downloads (chutku/models.py), made on first use
        self.telegram = None           # H16 Telegram gateway (chutku/gateway/telegram.py), when a token is stored
        self.enroll_clips = []         # Owner Voice Lock enrollment in progress (memory only)
        super().__init__(("127.0.0.1", port), DashboardHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    def service_actions(self):
        self.loop_tick = awake_clock()   # the HTTP loop is alive; the heartbeat thread reports it to the guard

    # The guard kills a core that is silent for 5 s. Beats used to come from this HTTP loop, so a few seconds of
    # GIL-heavy speech work or Windows background throttling looked like a hang (2026-10-28). Beats now come from
    # their own thread and stop only when the loop has been stuck for LOOP_STALL seconds: a real hang still ends.
    FILLER_AFTER = 1.2   # seconds without an answer before a spoken "ek second" (W3)
    LOOP_STALL = 30.0
    HANG_DUMP_AFTER = 8.0

    def process_request(self, request, client_address):
        """Each request runs on a reused pool thread instead of a new thread. Starting a thread on Windows waits for
        the loader lock, which another thread loading a DLL (screen capture, OCR, a model) can hold for seconds: the
        HTTP loop sat inside Thread.start for 8 s at a time (hang dumps 2026-11-05..09, 116k threads started)."""
        from concurrent.futures import ThreadPoolExecutor
        with self.queue_lock:
            if getattr(self, "_pool", None) is None:
                # 64: event streams hold a worker up to 55 s each (page, HUD, phone)
                self._pool = ThreadPoolExecutor(max_workers=64, thread_name_prefix="chutku-http")
        self._pool.submit(self.process_request_thread, request, client_address)

    def server_close(self):
        self.closing.set()   # ends the heartbeat and healing threads
        super().server_close()
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.shutdown(wait=True)   # like the per-request threads before: finish what is in flight

    def start_heartbeat(self, interval=0.5):
        if self.heartbeat is None:
            return None
        self.loop_tick = awake_clock()

        def run():
            dumped = False
            while not self.closing.wait(interval):
                stalled = awake_clock() - self.loop_tick
                if stalled >= self.HANG_DUMP_AFTER and not dumped:
                    dumped = True
                    dump_hang(self.base, stalled)
                elif stalled < min(1.0, self.HANG_DUMP_AFTER / 2):   # moving again: a later stall dumps anew
                    dumped = False
                if stalled >= self.LOOP_STALL:
                    continue   # stuck for real: stay silent so the guard restarts the core
                try:
                    self.heartbeat.send({"type": "heartbeat", "action_started": self.action_started})
                except (OSError, ValueError):
                    return     # the guard is gone
        thread = threading.Thread(target=run, name="chutku-heartbeat", daemon=True)
        thread.start()
        return thread


    def prime_brain(self):
        """Warm the local model in the background so the first request is fast."""
        def work():
            try:
                from chutku.agent_loop import prime
                lead = self.planners()[0]
                if str(getattr(lead, "name", "")).startswith("cloud"):
                    return   # the cloud plans first: keep the GPU free (the local model loads only when needed)
                with create_runtime(self.base) as runtime:
                    prime(runtime, lead)
            except Exception:
                _log().warning("warming the local model failed", exc_info=True)  # the first request retries
        threading.Thread(target=work, name="chutku-brain-prime", daemon=True).start()


    MAX_PARALLEL = 4   # App Mastery 2 (owner: "4 tasks: I do 2, Chutku does 2"); was 2 before the lanes
    STEP_WAIT = 180   # seconds a step waits for the other task's step before it gives up


    def _run_work(self, session, action, *, side=False):
        """The caller holds the action lock; it is released when the work ends, then the next order starts.
        A side task (side=True, see _parallel) holds a parallel slot instead and leaves the guard's timer alone."""
        if not side:
            self.action_started = time.monotonic()
            self.main_session = session   # H18: "aur haan, ..." steers this one
        with self.queue_lock:
            self.batch.append(session)
        with session.lock:
            if session.status == "queued":
                session.status = "planning"

        def beat():
            if not side:
                self.action_started = time.monotonic()

        def work():
            if not side:   # the heal message names the main task only
                record_last_task(self.base, session.goal, "running")
            try:
                with create_runtime(self.base) as runtime:
                    runtime.approvals = self.approvals
                    runtime.step_wait = self.STEP_WAIT   # a step waits for a side-by-side task's step to finish
                    router = RuntimeRouter(runtime, opener=lambda grant_id: create_runtime(self.base, grant_id))
                    progress.set_hook(beat, lambda: session.status == "cancelled" or session.cancelled.is_set())
                    try:
                        action(router, beat)
                        try:  # a fully verified plan becomes a worked example for similar requests
                            from chutku import experience, learning, reflex
                            recorded = experience.record(self.base, session, runtime)
                            learning.after_session(self.base, session, runtime)   # failed wording -> what worked
                            reflex.after_session(self.base, session, runtime, recorded)   # learned instant skills
                            from chutku import learning_inbox   # H10/H11/H12: proposals wait for the owner's OK
                            learning_inbox.after_session(self.base, session)
                        except (OSError, ValueError, KeyError):
                            pass
                    finally:
                        progress.set_hook()
                        router.close()
            except Exception as error:  # pause, stop or failure ends the session visibly
                from chutku.core.action_control import ActionsPaused
                message = paused_explanation(self.base) if isinstance(error, ActionsPaused) else f"Stopped: {error}"
                with session.lock:
                    if session.status != "cancelled":  # the owner's "stop" already ended it: keep "cancelled"
                        session._finish("failed", message[:400])
            finally:
                if side:
                    with self.queue_lock:
                        self.parallel_running -= 1
                else:
                    record_last_task(self.base, session.goal, session.status)
                    self.action_started = None
                    self.main_session = None
                    self.action_lock.release()
                    self._next_work()

        threading.Thread(target=work, name="chutku-side-task" if side else "chutku-agent", daemon=True).start()

    # -- W5: first-run setup (the page in chutku/web; the same steps as `chutku.cli setup`) ----------------------
    SETUP_ACTIONS = {"assistant", "name", "key", "mic", "mode", "download", "phone", "browser_login", "finish",
                     "reopen", "permission", "forget_approval"}


    def automation_action(self, data):
        """create (blueprint name + slots) or cancel (id). The owner's click is the request: the real task.schedule /
        task.cancel tools run through the policy kernel as user-stated steps."""
        from chutku import blueprints
        action = data.get("action") if isinstance(data, dict) else None
        if action == "create":
            slots = data.get("slots") or {}
            if not isinstance(slots, dict) or not all(isinstance(v, str) for v in slots.values()):
                raise ValueError("Slots must be text.")
            steps = blueprints.build(str(data.get("name", "")), slots)
            calls = [("task.schedule", step["arguments"]) for step in steps]
        elif action == "cancel" and isinstance(data.get("id"), str) and data["id"]:
            calls = [("task.cancel", {"id": data["id"]})]
        else:
            raise ValueError("Give action create (name, slots) or cancel (id).")
        with create_runtime(self.base) as runtime:
            runtime.approvals = self.approvals
            results = [runtime.run(tool, arguments, provenance="user_stated") for tool, arguments in calls]
        failed = [r for r in results if str(r.get("state")) != "COMPLETED"]
        if failed:
            if calls[0][0] == "task.cancel":   # review: a double click or a stale list said only "FAILED"
                return {**self.automations_view(), "note": "That automation was already gone."}
            raise ValueError(str(failed[0].get("error") or failed[0].get("reason") or failed[0].get("state"))[:300])
        return self.automations_view()


    def stop_session(self, session_id):
        session = self.agent_sessions.get(session_id)
        with create_runtime(self.base) as runtime:
            runtime.approvals = self.approvals
            return session.cancel(RuntimeRouter(runtime, opener=lambda g: create_runtime(self.base, g)))


    def confirm_session(self, session_id, approve, always=False):
        """The user's on-screen decision (web page or HUD button) for the one pending step. always (WA1): remember
        this exact step once it verifies, so it does not ask again (only from the laptop's own page)."""
        if type(approve) is not bool:
            raise ValueError("Provide an explicit approve true/false decision.")
        session = self.agent_sessions.get(session_id)
        planner, fallback = self.planners(getattr(session, "brain", None))

        def resolve(router, beat):
            from chutku import recall
            try:
                session.decide(router, approve=approve, always=always)
                session.advance(router, planner, fallback=fallback, heartbeat=beat)
                speak_result(session, router)
            finally:
                recall.log_session(session.snapshot(), base=self.base)   # approved tasks are remembered too
        with session.lock:
            if session.pending is None or session.status != "waiting_confirmation":
                raise ValueError("No confirmation is pending for this session.")
            session.status = "running"  # visible immediately; the worker resolves the exact step
        try:
            self.start_agent_work(session, resolve)
        except ExecutionBusy:
            with session.lock:
                session.status = "waiting_confirmation"
            raise
        return session.snapshot()

    # -- voice and hands-free ----------------------------------------------------
    def voice_request(self, mode, transcript=None):
        """Capture (unless a transcript is given) and start a voice session.

        Returns (session or None, transcript, message).
        """
        if transcript is None:
            if not self.action_lock.acquire(blocking=False):
                raise ExecutionBusy("Another action is running. Wait for it to finish.")
            wake = self.wake
            if wake is not None:
                wake.busy.set()  # one utterance must never trigger two requests
            try:
                with create_runtime(self.base) as runtime:
                    heard = runtime.run("voice.listen_command", {})
            finally:
                self.action_lock.release()
                if wake is not None and not getattr(wake, "handling", False):
                    wake.busy.clear()
            output = heard.get("output") or {}
            transcript = output.get("transcript")
            if not transcript:
                return None, None, (output.get("message") or heard.get("error") or "No confident speech was heard.")
        return self.begin_session(transcript, mode, "voice"), transcript, None

    def _speak(self, text):
        try:
            with create_runtime(self.base) as runtime:
                runtime.run("voice.speak", {"text": text[:1000]}, provenance="tool_observed")
        except Exception:
            _log().exception("speaking failed")

    def _say(self, text):
        """Speak without the runtime: voice.speak is a tool, and every tool is refused while paused. Used only
        for Chutku's own fixed sentences about the pause, never for content she read."""
        if not self.voice_replies:
            return
        from chutku.voice import tts
        from chutku.voice.session import voice_session
        try:
            with voice_session.active("speaking"):
                if tts.available():
                    try:
                        tts.speak(text[:400])
                        return
                    except Exception:
                        _log().exception("Kokoro failed; using the Windows voice")
                from chutku.tools.speech import _speak_sapi
                _speak_sapi({"text": text[:400]})
        except Exception:
            _log().exception("speaking while paused failed")   # the HUD still shows the reason

    def _wait_for(self, session, seconds=240):
        """Follow a voice task; each step that needs approval is asked out loud and answered by voice."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            snapshot = session.snapshot()
            status = snapshot["status"]
            if status == "waiting_confirmation":
                if snapshot.get("speaker_verified") is False:   # voice lock: not the owner's voice, screen only
                    self._hud_set("confirm", message="Voice not recognised as the owner's: approve on screen. "
                                                     "If it was you, press 'That was me' in the Voice lock tab.")
                    return
                if not self._approve_by_voice(session, snapshot):
                    return  # unclear twice: the HUD/page buttons still work
                continue
            if status in {"done", "clarify", "failed", "stopped", "cancelled"}:
                return
            time.sleep(0.3)


    def voice_enroll(self, action):
        """Owner Voice Lock enrollment from the dashboard: record one prompted line at a time (memory only)."""
        from chutku.voice import speaker
        if action == "status":   # opening the tab (2026-11-08: it fell through to "Unknown action.")
            pass
        elif action == "reset":
            self.enroll_clips = []
        elif action == "clip":
            if not self.action_lock.acquire(blocking=False):
                raise ExecutionBusy("Another action is running. Wait for it to finish.")
            wake = self.wake
            if wake is not None:
                wake.busy.set()   # the wake listener must not treat the line as a request
            try:
                from chutku.voice import recognition
                pcm = recognition.capture(ActionControl(self.base))["pcm"]
            finally:
                self.action_lock.release()
                if wake is not None:
                    wake.busy.clear()
            seconds = speaker.voiced_seconds(pcm)
            if seconds >= 2.0:
                self.enroll_clips.append(pcm)
            result = {"heard_seconds": round(seconds, 1), "ok": seconds >= 2.0}
        elif action == "finish":
            used = speaker.enroll(self.base, self.enroll_clips)
            self.enroll_clips = []
            result = {"enrolled_with": used}
        elif action == "that_was_me":   # the owner's click: the last rejected voice request was really them
            result = {"learned": speaker.that_was_me(self.base)}
        elif action in {"lock_on", "lock_off"}:
            if action == "lock_on" and speaker.load_voiceprint(self.base) is None:
                raise ValueError("Enroll your voice first.")
            self.preferences.update({"voice_lock": action == "lock_on"})
        else:
            raise ValueError("Unknown action.")
        enabled, threshold = speaker.settings(self.base)
        pending = speaker.last_rejected["embedding"] is not None and             time.monotonic() - speaker.last_rejected["at"] <= speaker.CONFIRM_SECONDS
        status = {"voice_lock": enabled, "enrolled": speaker.load_voiceprint(self.base) is not None,
                  "threshold": threshold, "clips": len(self.enroll_clips), "lines": speaker.ENROLL_LINES,
                  "learning": speaker.learning_stats(self.base), "rejected_waiting": pending,
                  "rejected_score": speaker.last_rejected["score"] if pending else None}
        return status | (result if action in {"clip", "finish", "that_was_me"} else {})

    def _speaker_check(self, source="local"):
        """Owner Voice Lock (S19): True/False for the voice that started this request; None when the lock is off."""
        try:
            from chutku.voice import speaker
            verified, score = speaker.verify_recent(self.base, source)
        except Exception:
            _log().exception("checking the voice failed")
            try:
                from chutku.voice import speaker
                verified, score = (False if speaker.settings(self.base)[0] else None), None   # on: fail closed
            except Exception:
                verified, score = None, None
        if verified is not None:
            _log().info("voice lock: owner=%s score=%s", verified, score)
        return verified


    def _listen_once(self, wait_seconds=None):
        """One short local transcript ("" when nothing clear was heard): an approval answer, or a follow-up within
        `wait_seconds` (W3) after she answered."""
        wake = self.wake
        if wake is not None:
            wake.busy.set()  # the wake listener must not treat the answer as a new request
        try:
            with create_runtime(self.base) as runtime:
                heard = runtime.run("voice.listen_command", {"wait_seconds": wait_seconds} if wait_seconds else {})
        except Exception:
            _log().exception("listening for an answer failed")
            return ""
        finally:
            if wake is not None and not getattr(wake, "handling", False):
                wake.busy.clear()
        return ((heard.get("output") or {}).get("transcript") or "").strip()


    END_CONVERSATION = re.compile(r"\W*(?:bas|bas karo|bye|ok bye|bye bye|thank you|thanks|that'?s all|ho gaya|"
                                  r"band karo|stop|rehne do|kuch nahi|nothing|no thanks)\W*", re.I)


    def memory_facts(self):
        from chutku.agent_loop import _user_facts
        with create_runtime(self.base) as runtime:
            return _user_facts(runtime)

    def memory_slice(self, topic, budget=800):
        """Topic-relevant memory for the voice model: sent once inside the setup message (no extra Gemini calls)."""
        from chutku import recall
        notes = [{"key": k, "value": v} for k, v in self.memory_facts().items()]
        return recall.about_you(topic, budget=budget, base=self.base, notes=notes)


    PHASES = ("idle", "listening", "thinking", "running", "speaking", "confirm", "done", "clarify", "error", "paused")
    MOODS = {"listening": "listening", "confirm": "listening", "clarify": "confused", "thinking": "thinking",
             "running": "thinking", "speaking": "speaking", "error": "sorry", "paused": "sleepy"}
    # shortcut: word cues in what she heard (Hindi script romanised first), not a sentiment model; upgrade if misread.
    LOVE = re.compile(r"\b(?:thanks?|thank\s*you|shukriya|dhanyava+d|love\s+(?:you|it)|pyaa?r|good\s+job|well\s+done|"
                      r"awesome|wah|badhiya|mast)\b", re.I)
    ANNOYED = re.compile(r"\b(?:stupid|useless|bakwaa?s|beka+r|pagal|idiot|ugh|galat|kya\s+kar\s+rahi|baar\s+baar|"
                         r"dimaa?g\s+kharab|shut\s+up)\b", re.I)


    def stop_everything(self):
        """Stop the running order and drop everything waiting in line. Returns how many orders were stopped."""
        with self.queue_lock:
            waiting, self.work_queue = list(self.work_queue), []
        stopped = 0
        for session, _action in waiting:
            with session.lock:
                if session.status == "queued":
                    session._finish("cancelled", "Stopped before it started.")
                    stopped += 1
        for session in list(self.agent_sessions.sessions.values()):
            if session.status in {"running", "planning", "waiting_confirmation"}:
                try:
                    self.stop_session(session.id)
                    stopped += 1
                except (ValueError, OSError):
                    pass
        return stopped

    def _control_session(self, goal, mode, origin, reply, *, status="done", silent=False):
        session = self.agent_sessions.add(AgentSession(goal, mode=mode, origin=origin, context={}))
        with session.lock:
            session._finish(status, reply)
        self.latest_session_id = session.id
        if origin == "voice" and not silent and self.voice_replies:   # a spoken request gets a spoken answer
            speak = self._say if ActionControl(self.base).paused else self._speak
            threading.Thread(target=speak, args=(reply,), name="chutku-control-reply", daemon=True).start()
        return session

    def _known_names(self):
        """People the owner taught Chutku (mind.json), so "mammi ko bolo" is a request even without a verb list hit."""
        try:
            from chutku import mind
            people = mind.Mind(self.base).load().get("people", [])
            return [n for p in people for n in [p.get("name", "")] + list(p.get("aliases", []))]
        except Exception:
            return []

    def begin_session(self, goal, mode, origin, *, silent=False, speaker_check=True, voice_source="local",
                      extra_context=None):
        from chutku import control_intent
        control = control_intent.kind(goal)
        busy = self.action_lock.locked() or bool(self.queued_ids())
        if control in ("stop", "pause"):
            from chutku.voice import tts
            tts.stop()   # "ruko" / "stop" also ends what Chutku is saying right now
        if control == "stop" and busy:
            count = self.stop_everything()
            return self._control_session(goal, mode, origin, f"Stopped ({count} task{'s' if count != 1 else ''}). "
                                                             "Completed steps stay; say \"undo that\" to reverse the last change.")
        if control == "restart":   # WA6: quit cleanly and come back (not paused)
            if self.heartbeat is None:
                return self._control_session(goal, mode, origin, "Main abhi restart nahi kar sakti: Chutku ka guard nahi "
                                                                 "chal raha. Chutku band karke Start menu se kholo.")
            from chutku import restart as restarting
            return self._control_session(goal, mode, origin, restarting.request(self.base))
        if control == "pause":
            ActionControl(self.base).pause("owner", "asked")
            self.stop_everything()
            return self._control_session(goal, mode, origin, "Paused. Nothing will run until you press Resume on the "
                                                             "dashboard or the tray, or say \"resume\" after Ctrl+Alt+Space.")
        if control == "resume" and ActionControl(self.base).paused:
            if origin != "text":   # a voice in the room may not lift a pause; the hotkey path handles spoken resume
                return self._control_session(goal, mode, origin, "Resume ke liye Ctrl+Alt+Space dabake \"resume\" bolo, "
                                                                 "ya dashboard ya tray mein Resume dabao.")
            ActionControl(self.base).resume()
            return self._control_session(goal, mode, origin, "Chalu ho gayi. Ab bolo, kya karna hai?")
        placement = None
        if busy and control is None:   # H18: "aur haan, ..." steers the running task; "baad mein karna" / "pehle ye karo"
            from chutku import busy as busy_mode
            kind, rest = busy_mode.route(goal)
            running = self.main_session
            if kind == "steer" and running is not None and busy_mode.add_note(running, rest):
                return self._control_session(goal, mode, origin, f"Theek hai, chal rahe kaam mein ye bhi jod diya: "
                                                                 f"\"{rest[:80]}\".", silent=silent)
            if kind in ("later", "first"):
                goal, placement = rest, kind
        from chutku.intents.tone import brain_choice
        brain, rest = brain_choice(goal)   # H9 "local se karo: ..." / "gemini se pucho ..."
        if brain is not None:
            goal = rest
            if brain == "cloud" and self.preferences.load().get("offline_mode"):   # fail closed: nothing leaves
                return self._control_session(goal, mode, origin, "Offline mode on hai, isliye main cloud ya Gemini "
                                             "se nahi poochungi. Pehle 'offline mode band karo' bolo.",
                                             status="clarify", silent=silent)
        from chutku import second_opinion
        recheck = second_opinion.rewrite(goal, self.base, origin)   # H22 "pakka?": a read-only re-check
        if recheck:
            goal = recheck
        if origin == "voice" and voice_source == "local" and control is None:
            from chutku.voice.plausible import plausible, read_back
            if not plausible(goal, known_names=self._known_names()):
                return self._control_session(goal, mode, origin, read_back(goal), status="clarify", silent=silent)
        with create_runtime(self.base) as runtime:
            context = default_context(RuntimeRouter(runtime, opener=lambda _grant: None))
        from chutku import recall
        notes = [{"key": k, "value": v} for k, v in (context.pop("user_facts", None) or {}).items()]
        try:   # what the owner told Chutku + earlier conversation, only the parts related to this goal
            context["about_you"] = recall.about_you(goal, budget=1200, base=self.base, notes=notes)
        except (OSError, ValueError, KeyError):
            context["about_you"] = {"facts": {n["key"]: n["value"] for n in notes}}
        from chutku import experience
        examples = experience.similar(self.base, goal)
        if examples:
            context["past_successes"] = examples
        from chutku.skill_import import relevant_procedures
        procedures = relevant_procedures(self.base, goal)
        if procedures:   # H11: names only; the planner reads one with skill.procedure before following it
            context["procedures"] = {"how": "To follow one, first read it with skill.procedure(name).",
                                     "items": procedures}
        from chutku.learning_inbox import relevant_lessons
        lessons = relevant_lessons(self.base, goal)
        if lessons:   # H10: past mistakes and their fixes for a similar goal: prefer the fix
            context["lessons"] = {"how": "Past mistakes on a similar request: use these tools, avoid those.",
                                  "items": lessons}
        if extra_context:   # e.g. a scheduled task's previous result (Phase 3b H8)
            context.update(extra_context)
        attached = None
        if origin in ("text", "script"):   # "@file:…", "@folder:…", "@url:…", "@clip" (Phase 3b H6): read before planning
            from chutku import references
            if references.find(goal):
                try:
                    with create_runtime(self.base) as runtime:
                        router = RuntimeRouter(runtime, opener=lambda grant_id: create_runtime(self.base, grant_id))
                        try:
                            goal, attachments, kinds = references.expand(goal, router)
                        finally:
                            router.close()
                except (references.ReferenceError, ValueError, OSError) as error:
                    return self._control_session(goal, mode, origin, f"I didn't attach that: {error}")
                attached = attachments
        from chutku.intents.tone import autonomy_for
        mode = autonomy_for(goal, mode)   # "bina puche kar do" -> trusted; "dhyan se" -> auto_safe (2026-11-06)
        session = self.agent_sessions.add(AgentSession(goal, mode=mode, origin=origin, context=context))
        if attached:   # each read becomes a completed step: taint, privacy and S15 line removal apply as usual
            with session.lock:
                for item in attached:
                    session._record(item["step"], item["result"])
        if origin == "voice" and speaker_check:   # a scheduled task was checked when it was ordered
            session.speaker_verified = self._speaker_check(voice_source)
        session.silent = silent   # set before any work starts: a live conversation narrates its own results
        session.observe_only = session.observe_only or bool(recheck)   # a re-check only reads
        from chutku.intents.tone import thinks
        session.think = thinks(goal)   # H21 "dhyan se socho": the strongest brain, with its full budget
        if self.planner_factory is None:
            from chutku.quick_intents import QuickPlanner
            from chutku.reflex import ReflexPlanner
            session.quick = QuickPlanner()
            session.reflex = ReflexPlanner(self.base)
        session.brain = brain
        planner, fallback = self.planners(brain)
        self.latest_session_id = session.id
        if brain == "cloud" and self.planner_factory is None and not str(getattr(planner, "name", "")).startswith(
                ("cloud", "gemini")):   # asked for the cloud, none is reachable: say so instead of planning locally
            with session.lock:
                session._finish("clarify", "Abhi koi cloud brain nahi mil raha (key nahi hai ya internet nahi hai). "
                                           "Bina 'gemini se' ke bolo to local model se kar dungi.")
            return session

        speech = SpeechQueue(self.base, goal) if origin == "voice" and not silent else None
        if speech is not None:
            session.on_sentence = speech.say   # first sentences are spoken while the answer is still being written

            def filler():
                # W3: a slow answer (a model round) starts with a short "ek second" so the owner knows she heard;
                # it goes through the same queue, so it can never talk over the answer.
                snapshot = session.snapshot()
                if snapshot["status"] in {"planning", "running", "queued"} and speech.spoken == 0 \
                        and speech.items.empty() and not snapshot["steps"]:
                    speech.say(FILLER)
            timer = threading.Timer(self.FILLER_AFTER, filler)
            timer.daemon = True
            timer.start()

        def run(router, beat):
            try:
                session.advance(router, planner, fallback=fallback, heartbeat=beat)
                if speech is not None:
                    speech.close()
                speak_result(session, router)
            finally:
                recall.log_session(session.snapshot(), base=self.base)   # remembered for later conversations
        self.start_agent_work(session, run, placement=placement)
        return session

    @property
    def url(self) -> str:
        # A fragment stays in the browser; it is not part of HTTP requests/logs.
        return f"{self.origin}/#token={self.token}"


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_):
        # Do not log URLs, tokens, command bodies or saved memory values.
        pass

    def _reply(self, code: int, data, content_type: str = "application/json; charset=utf-8"):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-src https://www.youtube-nocookie.com; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    EVENTS_SECONDS = 55     # a stream ends after this; the page reconnects (the server never waits long on shutdown)

    def _events(self, session_id):
        """Server-sent updates for one task (or the latest-task/hands-free state): pushed the moment they change,
        instead of the page asking every 0.6 s. The page reads it with fetch(), so the token stays in a header."""
        session = None
        if session_id:
            session = self.server.agent_sessions.get(session_id)   # unknown id: ValueError -> 404
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        last, started, pinged = None, time.monotonic(), time.monotonic()
        try:
            while time.monotonic() - started < self.EVENTS_SECONDS:
                payload = ({"session": session.snapshot()} if session is not None else
                           {"id": self.server.latest_session_id, "handsfree": self.server.handsfree_status()})
                text = json.dumps(payload, ensure_ascii=False, default=str)
                if text != last:
                    self.wfile.write(b"data: " + text.encode("utf-8") + b"\n\n")
                    self.wfile.flush()
                    last = text
                    if session is not None and payload["session"]["status"] in {
                            "done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation"}:
                        return
                elif time.monotonic() - pinged > 10:
                    self.wfile.write(b": ping\n\n")   # keeps the connection alive through quiet stretches
                    self.wfile.flush()
                    pinged = time.monotonic()
                time.sleep(0.2)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            return   # the page went away

    def _discard_bounded_body(self):
        # Windows may reset a connection closed with unread POST data, hiding
        # the intended refusal. Discard only a bounded body, without parsing it.
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if 0 < length <= 262144 and not self.headers.get("Transfer-Encoding"):
                self.rfile.read(length)
        except (ValueError, OSError):
            pass

    def _authorized(self, mutation: bool = False) -> bool:
        token = self.headers.get("X-Chutku-Token", "")
        origin = self.headers.get("Origin")
        return (self._host_ok() and token.isascii() and secrets.compare_digest(token, self.server.token)
                and self.headers.get("Sec-Fetch-Site") != "cross-site"
                and (origin == self.server.origin if mutation else origin in (None, self.server.origin)))

    def _remote_post(self, data):
        """W6 Phone panel (laptop only: needs this dashboard's token)."""
        remote = self.server.remote
        action = data.get("action")
        if action in ("boot_on", "boot_off"):   # 2026-11-08: one Windows prompt runs the setup or its removal
            from chutku.remote import boot
            self._reply(200, boot.run(self.server.base, action == "boot_on"))
            return
        if remote is None:
            self._reply(409, {"error": "Phone access is available only in the running Chutku."})
            return
        if action == "connect":   # owner 2026-11-08: one button does every missing step, in order
            self._reply(200, remote.connect())
        elif action == "enable":
            self._reply(200, remote.enable())
        elif action == "disable":
            self._reply(200, remote.disable())
        elif action == "pair":
            self._reply(200, remote.pair_code())
        elif action in ("arm", "disarm"):
            self._reply(200, remote.arm(action == "arm"))
        elif action == "revoke" and isinstance(data.get("device_id"), str):
            self._reply(200, remote.revoke(data["device_id"]))
        else:
            self._reply(400, {"error": "Choose connect, enable, disable, pair, arm, disarm, revoke, boot_on "
                                       "or boot_off."})

    def do_GET(self):
        if not self._host_ok():
            self._reply(403, {"error": "Invalid host."})
            return
        parts = urlsplit(self.path)
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/chutku.ico": ("chutku.ico", "image/x-icon"),
                  "/icon.png": ("icon.png", "image/png"),
                  "/logo.svg": ("logo.svg", "image/svg+xml"),
                  "/theme.css": ("theme.css", "text/css; charset=utf-8"),
                  "/say.json": ("say.json", "application/json; charset=utf-8"),
                  "/presence": ("presence.html", "text/html; charset=utf-8"),
                  "/presence.js": ("presence.js", "text/javascript; charset=utf-8"),
                  "/presence.css": ("presence.css", "text/css; charset=utf-8"),
                  "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json")}
        if parts.path in static:
            file, mime = static[parts.path]
            self._reply(200, (Path(__file__).parent / "web" / file).read_bytes(), mime)
            return
        if parts.path == "/help":   # W7: the user guide (public text, like the page itself)
            from chutku.core.paths import CODE_ROOT
            from chutku.help_page import render   # 2026-11-08 review: a page, not raw Markdown
            self._reply(200, render((CODE_ROOT / "docs" / "USER_GUIDE.md").read_text(encoding="utf-8")),
                        "text/html; charset=utf-8")
            return
        if not self._authorized():
            self._reply(403, {"error": "Open the complete dashboard link printed by Chutku, including its session token."})
            return
        try:
            if parts.path == "/api/events":
                self._events(parse_qs(parts.query).get("id", [""])[0])
                return
            # The polled endpoints only read in-memory sessions: no runtime (5 databases, 148 tools) per poll.
            if parts.path == "/api/agent/latest":
                self._reply(200, {"id": self.server.latest_session_id, "handsfree": self.server.handsfree_status()})
                return
            if parts.path == "/api/agent/session":
                session = self.server.agent_sessions.get(parse_qs(parts.query).get("id", [""])[0])
                self._reply(200, {"session": session.snapshot()})
                return
            if parts.path == "/api/automations":   # W6: blueprints and the scheduled automations (files only)
                self._reply(200, self.server.automations_view())
                return
            if parts.path == "/api/setup":   # W5: the first-run page (polled while packs download): no runtime
                self._reply(200, self.server.setup_view())
                return
            if parts.path == "/api/presence":   # polled ~10x a second by the presence orb: memory only
                self._reply(200, self.server.presence_state())
                return
            if parts.path == "/api/update":     # 2026-11-08: the "update available" popup (cached 6 h)
                from chutku import updates
                self._reply(200, updates.check())
                return
            if parts.path == "/api/remote":     # W6: the Phone panel
                from chutku.remote import boot
                remote = self.server.remote
                self._reply(200, {**(remote.status() if remote is not None else {"enabled": False, "running": False,
                                                                                 "available": False}),
                                  "boot": boot.status()})   # 2026-11-08: "Reach this laptop after a restart"
                return
            with create_runtime(self.server.base) as runtime:
                if parts.path == "/api/state":
                    from chutku.evidence import read_evidence
                    from chutku.voice.session import voice_session
                    from chutku.voice.heard import recent_heard
                    response = (200, {"tools": capabilities(runtime.registry), "limits": LIMITS,
                        "history": runtime.event_log.recent_tasks(20), "memories": runtime.memory.search(),
                        "sandbox": str(runtime.granted_root), "mode": "Local · deterministic",
                        "resource_grant": runtime.current_grant().public(),
                        "resource_grants": [grant.public() for grant in runtime.resource_grants.list()],
                        "actions_paused": runtime.action_control.paused,
                        "guard_active": self.server.heartbeat is not None,
                        "voice_session": voice_session.snapshot().__dict__,
                        "verification": read_evidence(self.server.base),
                        "autonomy_modes": [mode.value for mode in AutonomyMode if mode != AutonomyMode.TRUSTED],
                        "handsfree": self.server.handsfree_status(),
                        "heard": recent_heard(30, base=self.server.base),
                        "capability_grants": [g.public() for g in runtime.capability_grants.list()]})
                elif parts.path == "/api/today":
                    from chutku.today import snapshot
                    from chutku import suggest
                    today = snapshot(self.server.base, runtime)
                    try:
                        today["suggestions"] = suggest.current(self.server.base)[:4]
                    except (OSError, ValueError, KeyError):
                        today["suggestions"] = []
                    response = (200, today | {
                        "board": self.server.board_view(),   # H15: research results and the owner's to-dos
                        "interrupted": interrupted_task(self.server.base),
                        "paused_reason": paused_explanation(self.server.base, short=True) if today["actions_paused"] else None})
                elif parts.path == "/api/board":
                    response = (200, self.server.board_view(include_done=True))
                elif parts.path == "/api/reliability":
                    response = (200, {"rows": runtime.ledger.table()})
                elif parts.path == "/api/reflexes":
                    from chutku import reflex
                    response = (200, reflex.summary(self.server.base))
                elif parts.path == "/api/mind":
                    from chutku.recall import mind_map
                    response = (200, mind_map(self.server.base))
                elif parts.path == "/api/agent/latest":
                    response = (200, {"id": self.server.latest_session_id,
                                      "handsfree": self.server.handsfree_status()})
                elif parts.path == "/api/agent/session":
                    session = self.server.agent_sessions.get(parse_qs(parts.query).get("id", [""])[0])
                    response = (200, {"session": session.snapshot()})
                elif parts.path == "/api/trace":
                    task_id = parse_qs(parts.query).get("id", [""])[0]
                    if len(task_id) > 100:
                        raise ValueError("Invalid task ID.")
                    response = (200, {"events": runtime.event_log.safe_trace(task_id)})
                else:
                    response = (404, {"error": "Unknown endpoint."})
        except ValueError as error:
            response = (404, {"error": str(error)})
        except Exception:
            ref = _error_ref("GET " + parts.path)
            response = (500, {"error": "Could not read local state. Check that the data directory is writable.",
                              "error_id": ref})
        self._reply(*response)

    def do_POST(self):
        if not self._authorized(mutation=True):
            # Drain small bounded bodies before closing: on Windows, closing with
            # unread POST bytes can reset the socket instead of delivering 403.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if 0 < length <= 4096 and not self.headers.get("Transfer-Encoding"):
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass
            self._reply(403, {"error": "Session, host or origin check failed."})
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json" or self.headers.get("Transfer-Encoding"):
            self._discard_bounded_body()
            self._reply(415, {"error": "Send a bounded JSON request."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 131072:
                self._discard_bounded_body()
                self._reply(413, {"error": "Request is empty or too large."})
                return
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object.")
        except (ValueError, UnicodeError):
            self._reply(400, {"error": "Invalid JSON request."})
            return
        # Pause remains reachable while an action owns the normal request lock.
        if urlsplit(self.path).path == "/api/control":
            if set(data) != {"action"} or data["action"] not in ("pause", "resume", "stop", "restart"):
                self._reply(400, {"error": "Choose pause, resume, stop or restart."})
                return
            if data["action"] == "restart":   # WA6: Settings > About "Restart Chutku" (never leaves it paused)
                if self.server.heartbeat is None:
                    self._reply(409, {"error": "Restart needs Chutku's guard, which is not running. Close Chutku and "
                                               "open it again from the Start menu."})
                    return
                from chutku import restart as restarting
                self._reply(200, {"restarting": True, "message": restarting.request(self.server.base)})
                return
            control = ActionControl(self.server.base)
            try:
                if data["action"] == "stop":
                    if self.server.heartbeat is None:
                        self._reply(409, {"error": "The emergency stop needs Chutku's guard, which is not running. "
                                                   "Close Chutku and open it again from the Start menu."})
                        return
                    control.stop()
                elif data["action"] == "pause":
                    control.pause()
                else:
                    control.resume()
                self._reply(200, {"actions_paused": control.paused})
            except (OSError, ExecutionBusy, ValueError):
                self._reply(409, {"error": "Could not change action control. Wait for the active action before resuming."})
            return
        # Capture cancellation remains reachable while listening owns the action lock.
        if urlsplit(self.path).path == "/api/voice/stop_speaking":   # stop Chutku mid-sentence
            from chutku.voice import tts
            tts.stop()
            self._reply(200, {"stopped": True})
            return
        if urlsplit(self.path).path == "/api/update":   # 2026-11-08: "Update now" (or "Check again")
            from chutku import updates
            action = data.get("action")
            try:
                if action == "check":
                    self._reply(200, updates.check(force=True))
                elif action == "install":
                    updates.install()
                    self._reply(200, updates.check())
                else:
                    self._reply(400, {"error": "Choose check or install."})
            except ValueError as error:
                self._reply(400, {"error": str(error)})
            return
        if urlsplit(self.path).path == "/api/remote":   # W6 Phone panel (laptop only: needs this dashboard's token)
            try:
                self._remote_post(data)
            except (OSError, subprocess.SubprocessError, ValueError) as error:   # 2026-11-08 review: a timeout
                # in "tailscale status" closed the connection with no answer and the page kept retrying
                self._reply(409, {"error": f"That did not work: {error}"})
            except Exception:
                self._reply(500, {"error": "Something went wrong.", "error_id": _error_ref("POST /api/remote")})
            return
        if urlsplit(self.path).path == "/api/presence/video/close":   # X13: the video's close button
            from chutku.tools.internet import hud_video_file
            hud_video_file(self.server.base).unlink(missing_ok=True)
            self._reply(200, {"video": None})
            return
        if urlsplit(self.path).path == "/api/presence/talk":   # the orb was clicked: the same as Ctrl+Alt+Space
            if data:
                self._reply(400, {"error": "Talk takes no arguments."})
                return
            threading.Thread(target=self.server.handsfree_request, name="chutku-orb-talk", daemon=True).start()
            self._reply(200, {"listening": True})
            return
        if urlsplit(self.path).path == "/api/voice/cancel":
            if data:
                self._reply(400, {"error": "Voice cancellation takes no arguments."})
                return
            from chutku.voice.session import voice_session
            cancelled = voice_session.cancel_capture()
            self._reply(200, {"capture_cancelled": cancelled, "voice_session": voice_session.snapshot().__dict__})
            return
        path = urlsplit(self.path).path
        if path in {"/api/chat", "/api/agent/confirm", "/api/agent/stop", "/api/voice/ask", "/api/preferences",
                    "/api/suggestions", "/api/reflexes", "/api/voice/enroll", "/api/nightshift", "/api/board/stop",
                    "/api/telegram", "/api/setup", "/api/automations", "/api/board"}:
            self._reply(*self._agent_post(path, data))
            return
        if not self.server.action_lock.acquire(blocking=False):
            self._reply(409, {"error": "Another action is running. Wait for it to finish."})
            return
        self.server.action_started = time.monotonic()
        try:
            with create_runtime(self.server.base) as runtime:
                path = urlsplit(self.path).path
                runtime.approvals = self.server.approvals
                if path == "/api/command":
                    if set(data) != {"message"} or not isinstance(data["message"], str) or not 1 <= len(data["message"]) <= 70000:
                        raise ValueError("Enter a command of 1 to 70000 characters.")
                    result = execute_request(data["message"], runtime)
                    voice_review_token = None
                    voice_plan = None
                    transcript = result.get("output", {}).get("transcript")
                    if isinstance(transcript, str):
                        from chutku.brain import preview_tool_plan
                        voice_plan = preview_tool_plan(transcript, runtime)
                        if voice_plan.get("steps"):
                            voice_review_token = self.server.voice_previews.add({
                                "plan": voice_plan, "source_task_id": result["task_id"]})
                        runtime.event_log.append(result["task_id"], "voice_review_created", {
                            "expires_in": self.server.voice_previews.ttl, "transcript": "[REDACTED]"})
                    response = (200, {"result": result, "message": present(result),
                                      "voice_plan": voice_plan, "voice_review_token": voice_review_token})
                elif path in {"/api/voice/execute", "/api/voice/review/cancel"}:
                    if set(data) != {"review_token"} or not isinstance(data["review_token"], str):
                        raise ValueError("Provide only the server-issued voice review token.")
                    if path.endswith("cancel"):
                        self.server.voice_previews.cancel(data["review_token"])
                        response = (200, {"cancelled": True})
                    else:
                        reviewed = self.server.voice_previews.take(data["review_token"])
                        execution_token = self.server.agent_executions.prepare(
                            reviewed["plan"], runtime, provenance="reviewed_microphone")
                        result = self.server.agent_executions.start(execution_token, runtime)
                        response = (200, {"result": result, "message": result["message"],
                                          "voice_source_task_id": reviewed["source_task_id"]})
                elif path in {"/api/approve", "/api/approval/cancel"}:
                    if set(data) != {"token"} or not isinstance(data["token"], str):
                        raise ValueError("Provide only the task-bound approval token.")
                    result = runtime.approve(data["token"], cancel=path.endswith("cancel"))
                    response = (200, {"result": result, "message": present(result)})
                elif path == "/api/brain/preview":
                    from chutku.brain import preview_tool_plan
                    if set(data) != {"message"} or not isinstance(data["message"], str) or not 1 <= len(data["message"]) <= 4000:
                        raise ValueError("Describe your request in 1 to 4000 characters.")
                    plan = preview_tool_plan(data["message"], runtime)
                    token = self.server.brain_previews.add(plan) if plan["steps"] else None
                    response = (200, {"plan": plan, "preview_token": token})
                elif path in {"/api/brain/execute", "/api/brain/cancel"}:
                    if set(data) != {"preview_token"} or not isinstance(data["preview_token"], str):
                        raise ValueError("Provide only a preview token.")
                    if path == "/api/brain/cancel":
                        self.server.brain_previews.cancel(data["preview_token"])
                        response = (200, {"cancelled": True})
                    else:
                        plan = self.server.brain_previews.take(data["preview_token"])
                        execution_token = self.server.agent_executions.prepare(
                            plan, runtime, provenance="reviewed_inferred")
                        result = self.server.agent_executions.start(execution_token, runtime)
                        response = (200, {"result": result, "message": result["message"]})
                elif path == "/api/agent/decision":
                    if (set(data) != {"execution_token", "approve"}
                            or not isinstance(data["execution_token"], str)
                            or type(data["approve"]) is not bool):
                        raise ValueError("Provide an execution token and an explicit approval decision.")
                    result = self.server.agent_executions.decide(
                        data["execution_token"], runtime, approve=data["approve"])
                    response = (200, {"result": result, "message": result["message"]})
                elif path == "/api/plan/preview":
                    from chutku.plans import build_plan
                    if set(data) != {"commands"}:
                        raise ValueError("Provide only the commands list.")
                    plan = build_plan(data["commands"], runtime)
                    token = self.server.sequence_previews.add(plan)
                    response = (200, {"plan": plan, "preview_token": token})
                elif path in {"/api/plan/execute", "/api/plan/cancel"}:
                    from chutku.plans import run_plan
                    if set(data) != {"preview_token"} or not isinstance(data["preview_token"], str):
                        raise ValueError("Provide only a preview token.")
                    if path == "/api/plan/cancel":
                        self.server.sequence_previews.cancel(data["preview_token"])
                        response = (200, {"cancelled": True})
                    else:
                        plan = self.server.sequence_previews.take(data["preview_token"])
                        result = run_plan(plan, runtime)
                        response = (200, {"result": result, "message": result["message"]})
                elif path == "/api/preview":
                    if set(data) != {"name"}:
                        raise ValueError("Provide only the project name.")
                    plan = project_plan(data["name"], runtime.granted_root)
                    preflight(plan, runtime)
                    token = self.server.previews.add(plan)
                    response = (200, {"plan": plan, "preview_token": token, "expires_in": self.server.previews.ttl})
                elif path in {"/api/execute", "/api/cancel"}:
                    if set(data) != {"preview_token"} or not isinstance(data["preview_token"], str):
                        raise ValueError("Provide only a preview token.")
                    if path == "/api/cancel":
                        self.server.previews.cancel(data["preview_token"])
                        response = (200, {"cancelled": True})
                    else:
                        plan = self.server.previews.take(data["preview_token"])
                        result = run_project(plan, runtime)
                        response = (200, {"result": result, "message": result["message"]})
                else:
                    response = (404, {"error": "Unknown endpoint."})
        except (ValueError, KeyError) as error:
            response = (400, {"error": str(error)})
        except Exception:
            ref = _error_ref("POST " + path)
            response = (500, {"error": "The action could not finish. Inspect history before retrying; completed steps "
                                       "may remain.", "error_id": ref})
        finally:
            self.server.action_started = None
            self.server.action_lock.release()
        # Commit/close storage and release the action lock before acknowledging it.
        self._reply(*response)


# Catalog commands answered instantly in chat. File and app requests go to the agent,
# which understands whole-drive paths and any installed app.
INSTANT_TOOLS = frozenset({
    "system.get_time", "system.environment", "system.gpu_status", "system.audio_devices",
    "assistant.capabilities", "windows.list", "memory.remember", "memory.search", "memory.forget",
    "filesystem.undo_last_write", "filesystem.undo_last_copy", "filesystem.undo_last_move",
    "filesystem.restore_last_recycled", "screen.undo_last_capture", "screen.displays",
    "voice.list_voices", "voice.recognition_status", "voice.audio_input_status", "voice.speak",
    "settings.earned_autonomy", "settings.voice_lock", "settings.timeline",
    "never.add", "never.list", "never.remove", "skill.approve", "evolve.approve", "evolve.reject",
    "settings.evolve_push",
    "background.pause", "background.resume", "background.status",
})


def _mode(data):
    mode = data.get("mode", AutonomyMode.REVIEW.value)
    if mode not in {m.value for m in AutonomyMode} or mode == AutonomyMode.TRUSTED:   # trusted: only the owner's words
        raise ValueError("Choose review, auto_safe, auto_edits or owner.")
    return mode


def _error_ref(where):
    """Log the current exception with a short id that the owner sees next to the error."""
    from chutku.core.log import error_id
    ref = error_id()
    _log().exception("error %s in %s", ref, where)
    return ref


def message_for_person(tool, message):
    """ "say good night to mammi" is a message to a person, not text to speak aloud (audit 2026-10-06)."""
    return tool == "voice.speak" and bool(re.search(r"\b(?:say|tell|bolo|bol do)\b.+\b(?:to|ko)\s+\w|"
                                                    r"\b\w+\s+ko\s+(?:bolo|bol do|bata do|batao)\b", message, re.I))


def _agent_post(self, path, data):
    """Chat/agent endpoints. Work runs on a worker thread; the UI polls the session."""
    server = self.server
    try:
        if path == "/api/chat":
            if set(data) - {"message", "mode"} or not isinstance(data.get("message"), str) \
                    or not 1 <= len(data["message"].strip()) <= 2000:
                raise ValueError("Enter a message of 1 to 2000 characters.")
            mode = _mode(data)
            # F7: scripts that drive the live Chutku (live_check, timing runs) say so; their turns are kept apart
            # from the owner's, so habits, suggestions, examples and the nightly replay learn from the owner only.
            origin = "script" if self.headers.get("X-Chutku-Synthetic") == "1" else "text"
            from chutku.planning import plan_request
            understood = plan_request(data["message"])
            from chutku import control_intent
            to_person = message_for_person(understood.tool, data["message"])
            if understood.state == "READY" and understood.tool in INSTANT_TOOLS and not server.action_lock.locked() \
                    and control_intent.kind(data["message"]) is None and not to_person:
                # Exact supported command: instant deterministic path (still policy-checked).
                if not server.action_lock.acquire(blocking=False):
                    raise ExecutionBusy("Another action is running. Wait for it to finish.")
                began = time.monotonic()
                try:
                    with create_runtime(server.base) as runtime:
                        runtime.approvals = server.approvals
                        result = execute_request(data["message"], runtime)
                finally:
                    server.action_lock.release()
                from chutku import recall
                recall.log_conversation(data["message"], present(result), origin=origin, base=server.base,
                                        status="done" if result.get("state") == "COMPLETED" else "failed",
                                        tools=[understood.tool] if result.get("state") == "COMPLETED" else [],
                                        planners=["direct"], seconds=time.monotonic() - began)
                return 200, {"kind": "direct", "result": result, "message": present(result)}
            session = server.begin_session(data["message"].strip(), mode, origin)
            return 200, {"kind": "agent", "session": session.snapshot()}
        if path == "/api/telegram":   # H16: pairing happens only here (the loopback dashboard) or in the CLI
            from chutku.gateway import telegram
            if data.get("action") == "token" and set(data) == {"action", "token"}:
                # 2026-11-08 the Phone tab's Telegram card: checked with Telegram, stored, never echoed back
                bot = telegram.connect_token(server.base, data["token"])
                if server.telegram is None:
                    server.telegram = telegram.start(server)   # no restart needed
                else:
                    server.telegram.transport = None           # the running poll picks up the new token
                return 200, {"token_stored": True, "bot": bot, "paired": telegram.paired(server.base) is not None}
            if set(data) != {"action"} or data["action"] not in {"status", "pair", "unpair"}:
                raise ValueError("Give action: status, token, pair or unpair.")
            gateway = telegram.Gateway(server.base, server)
            if data["action"] == "pair":
                code = gateway.new_code()
                try:
                    bot = gateway.bot_name()
                except telegram.TelegramError:   # offline: typing /pair CODE still works
                    bot = None
                link = f"https://t.me/{bot}?start={code}" if bot else None
                from chutku.remote.manager import qr_svg
                return 200, {"code": code, "send_to_bot": "/pair <code>", "valid_minutes": 60, "bot": bot,
                             "link": link, "qr_svg": qr_svg(link) if link else None}
            if data["action"] == "unpair":
                gateway.unpair()
            return 200, {"token_stored": bool(telegram.token()), "paired": telegram.paired(server.base) is not None,
                         "bot": telegram.load(server.base).get("bot"),
                         "handoff": gateway.handed_off(), "running": server.telegram is not None,
                         "error": getattr(server.telegram, "last_error", None)}
        if path == "/api/automations":   # W6: create from a blueprint, or cancel
            return 200, server.automation_action(data)
        if path == "/api/board":   # W6: the Board tab's done / again / archive buttons
            return 200, server.board_action(data)
        if path == "/api/setup":   # W5: one first-run step (the key is stored, never echoed back)
            return 200, server.setup_action(data)
        if path == "/api/board/stop":   # H15: the running-workers strip's Stop button
            if set(data) != {"id"} or type(data["id"]) is not int:
                raise ValueError("Give the board task id.")
            stopped = server.board is not None and server.board.stop_task(data["id"])
            return 200, {"stopped": stopped, "board": server.board_view(include_done=True)}
        if path == "/api/suggestions":
            from chutku import suggest
            if set(data) != {"id", "action"}:
                raise ValueError("Give id and action.")
            return 200, suggest.respond(server.base, data["id"], data["action"])
        if path == "/api/nightshift":   # Night Shift (S20): run the nightly jobs here, sharing this process's model
            if set(data) != {"action"} or data["action"] != "run":
                raise ValueError("Give action: run.")
            return 200, server.run_nightshift()
        if path == "/api/voice/enroll":   # Owner Voice Lock tab: status, record a line, finish, lock on/off
            if set(data) != {"action"} or data["action"] not in {"status", "reset", "clip", "finish", "lock_on",
                                                                  "lock_off", "that_was_me"}:
                raise ValueError("Give an action: status, reset, clip, finish, lock_on, lock_off or that_was_me.")
            return 200, server.voice_enroll(data["action"])
        if path == "/api/reflexes":   # the owner switches a learned skill on or off (Skills tab)
            from chutku import reflex
            if set(data) != {"id", "enabled"} or not isinstance(data["id"], str) or type(data["enabled"]) is not bool:
                raise ValueError("Give id and enabled true/false.")
            if reflex.set_enabled(server.base, data["id"], data["enabled"]) is None:
                raise ValueError("No such skill.")
            return 200, reflex.summary(server.base)
        if path == "/api/voice/ask":
            if set(data) - {"mode"}:
                raise ValueError("Voice requests take only a mode.")
            session, transcript, message = server.voice_request(_mode(data))
            if session is None:
                return 200, {"kind": "voice", "transcript": None, "message": message}
            return 200, {"kind": "agent", "transcript": transcript, "session": session.snapshot()}
        if path == "/api/preferences":
            if data.get("voice_lock") is True:
                from chutku.voice import speaker
                if speaker.load_voiceprint(server.base) is None:
                    raise ValueError("Enroll your voice first (Voice lock tab).")
            values = server.preferences.update(data)
            if "wake_word" in data:
                server.apply_wake(values["wake_word"])
            return 200, {"handsfree": server.handsfree_status()}
        if set(data) - {"id", "approve", "always"} or not isinstance(data.get("id"), str):
            raise ValueError("Provide the session id.")
        if path == "/api/agent/stop":
            return 200, {"session": server.stop_session(data["id"])}
        if type(data.get("approve")) is not bool or type(data.get("always", False)) is not bool:
            raise ValueError("Provide an explicit approve true/false decision.")
        # WA1 "Yes, always": only from this laptop page (the phone and Telegram call confirm_session without it)
        return 200, {"session": server.confirm_session(data["id"], data["approve"],
                                                       always=data.get("always") is True and data["approve"] is True)}
    except ExecutionBusy as error:
        return 409, {"error": str(error)}
    except (ValueError, KeyError) as error:
        return 400, {"error": str(error)}
    except Exception:
        return 500, {"error": "The request could not be started. Inspect Activity before retrying.",
                     "error_id": _error_ref("agent " + path)}


DashboardHandler._agent_post = _agent_post


def awake_clock():
    """Seconds the PC was awake. time.monotonic() keeps counting through Windows sleep, so every wake-up looked like
    a hang as long as the sleep (2898.9 s on 2026-11-09) and the core was restarted; QueryUnbiasedInterruptTime
    leaves sleep and hibernate out."""
    if os.name == "nt":
        import ctypes
        ticks = ctypes.c_ulonglong()
        if ctypes.windll.kernel32.QueryUnbiasedInterruptTime(ctypes.byref(ticks)):
            return ticks.value / 1e7
    return time.monotonic()


def dump_hang(base, stalled, keep=10):
    """Every thread's stack when the core's loop stops moving, so a hang can be diagnosed afterwards
    (data/logs/hang-*.txt, newest `keep` kept). Returns the file, or None."""
    import faulthandler
    folder = Path(base) / "data" / "logs"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"hang-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        with path.open("w", encoding="utf-8") as stream:
            stream.write(f"Chutku's HTTP loop has not moved for {stalled:.1f} s.\nThreads (id -> name):\n")
            for thread in threading.enumerate():   # faulthandler prints ids only
                stream.write(f"  0x{thread.ident or 0:016x} {thread.name}\n")
            stream.write("\n")
            stream.flush()
            faulthandler.dump_traceback(stream, all_threads=True)
        for old in sorted(folder.glob("hang-*.txt"))[:-keep]:
            old.unlink(missing_ok=True)
        _log().warning("loop stalled %.1f s; stacks in %s", stalled, path)
        return path
    except OSError:
        return None


def record_last_task(base, goal, status):
    """Remember the latest agent goal and its status, so a crash mid-task can be offered for retry."""
    from chutku import control_intent
    if control_intent.kind(goal) is not None:
        return  # "do it again" / "undo" must not replace the request they refer to
    path = _last_task_file(base)
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    started = previous.get("started") if previous.get("goal") == goal and status != "running" else time.time()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"goal": str(goal)[:2000], "status": str(status), "started": started}),
                             encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass  # recovery hints are best-effort


def mark_interrupted_task(base):
    """At start-up: a task still marked running was cut off by a crash or stop."""
    path = _last_task_file(base)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if record.get("status") in {"running", "planning"}:
        record["status"] = "interrupted"
        path.write_text(json.dumps(record), encoding="utf-8")
        return record
    return None


def _session_file(base):
    return Path(base) / "data" / "dashboard-session.json"


def _write_session_link(base, url):
    """Remember this session's link (it carries the session token) so `chutku open` can reach it later."""
    path = _session_file(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"url": url, "pid": os.getpid()}), encoding="utf-8")
    os.replace(temporary, path)


def open_running_dashboard(base=PROJECT_ROOT, opener=None):
    """Open the live dashboard if one is running; otherwise say how to start it."""
    import urllib.request
    try:
        url = json.loads(_session_file(base).read_text(encoding="utf-8"))["url"]
    except (OSError, ValueError, KeyError):
        return "Chutku is not running. Start it with Start-Chutku.cmd."
    origin = url.split("#", 1)[0]
    try:
        urllib.request.urlopen(origin, timeout=3).close()  # only the static page; the token stays in the fragment
    except OSError:
        return "Chutku is not running. Start it with Start-Chutku.cmd."
    (opener or open_app_window)(url)
    return "Opened the Chutku dashboard."


def _warm_app_list():
    """Read the Start-menu app list and start the OCR worker at startup, so first uses do not wait."""
    from chutku.tools.documents import warm_ocr
    from chutku.tools.everyday import start_apps
    try:
        start_apps()
    except OSError:
        pass  # read again on first use
    warm_ocr()  # keeps the Windows OCR engine loaded: screen reads take ~0.1 s instead of ~0.6 s


def serve(port: int = 8765, open_browser: bool = False, *, base=PROJECT_ROOT, heartbeat=None):
    with DashboardServer(base=base, port=port, heartbeat=heartbeat) as server:
        server.start_heartbeat()   # before the slow start-up work: a hang there is caught too
        mark_interrupted_task(base)
        server.prime_brain()
        server.start_handsfree()
        if not server.start_presence():
            server.start_hud()
        if Path(base).resolve() == Path(PROJECT_ROOT).resolve():  # the real install, not a throwaway demo state
            import threading
            from chutku.health import watch
            threading.Thread(target=watch, args=(base, threading.Event()), name="chutku-health", daemon=True).start()
            from chutku import suggest
            threading.Thread(target=suggest.watch, args=(base, threading.Event()), name="chutku-suggest",
                             daemon=True).start()
            threading.Thread(target=_warm_app_list, name="chutku-apps-warm", daemon=True).start()
            from chutku.voice import tts
            threading.Thread(target=tts.warm_up, name="chutku-tts-warm", daemon=True).start()   # neural voice ready
            def night_shift_on():   # owner 2026-11-08: practice and learning every night, on by default
                try:
                    from chutku import nightshift
                    from chutku.core.paths import CODE_ROOT
                    nightshift.ensure_installed(CODE_ROOT)
                except Exception:
                    _log().exception("could not install the Night Shift task")
            threading.Thread(target=night_shift_on, name="chutku-nightshift-install", daemon=True).start()
            from chutku import timeline
            threading.Thread(target=timeline.watch, args=(base, threading.Event()), name="chutku-timeline",
                             daemon=True).start()   # opt-in ("timeline on"): window titles only, 14 days
            from chutku import know_me   # what the owner watches, opens and visits (local, every 6 h)
            threading.Thread(target=know_me.watch, args=(base, threading.Event()), name="chutku-know-me",
                             daemon=True).start()
            from chutku import scheduled
            threading.Thread(target=scheduled.watch, args=(server, threading.Event()), name="chutku-scheduled",
                             daemon=True).start()   # "30 min baad ...", "har 15 min ...": runs beside normal work
            server.start_board()   # H15: "research karke batao ..." runs in the background
            from chutku.gateway import telegram
            server.telegram = telegram.start(server)   # H16: only when a bot token is stored
            server.start_tray()
        server.heal_when_healthy()
        server.start_remote()
        _write_session_link(base, server.url)
        if Path(base).resolve() == Path(PROJECT_ROOT).resolve():   # 2026-11-08: chutku.localhost opens this dashboard
            from chutku import alias
            alias.start(lambda: server.url)
        # The token stays out of stdout: the guard copies stdout into data/logs (release review 2026-11-07).
        print(f"Chutku is ready at {server.origin}/ (open it with `chutku.cli open`; the session link is in "
              "data/dashboard-session.json).", flush=True)
        print("Keep this terminal running. Press Ctrl+C to stop. Planning is local; Gemini is used only if you granted cloud.gemini.", flush=True)
        if open_browser:
            open_app_window(server.url)
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            print("\nChutku dashboard stopped.")

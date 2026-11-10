"""Dashboard work: the request queue, parallel work, setup, automations, the task board, night shift (DashboardWork)."""
from __future__ import annotations

from pathlib import Path
import threading
import time

from chutku.agent_loop import LocalAgentPlanner
from chutku.app import PROJECT_ROOT
from chutku.core.action_control import ActionControl
from chutku.core.execution_lock import ExecutionBusy
from chutku.dashboard_helpers import _log, interrupted_task
from chutku.policy.kernel import AutonomyMode


MAX_QUEUED = 10


class DashboardWork:
    """Methods of DashboardServer, kept here to keep dashboard.py short."""

    def heal_when_healthy(self, healthy_for=30.0, retry=10.0, give_up=600.0):
        """After the guard restarted this core, lift the guard's own pause once the core has stayed up
        `healthy_for` seconds, and say so. The owner's pause is never lifted; the cut-off task is not re-run."""
        if self.heartbeat is None:
            return None

        def run():
            if self.closing.wait(healthy_for):
                return
            deadline = time.monotonic() + give_up
            while time.monotonic() < deadline:
                try:
                    lifted = ActionControl(self.base).heal()
                    break
                except ExecutionBusy:
                    if self.closing.wait(retry):
                        return
            else:
                return
            if lifted is None:
                return
            _log().info("lifted the guard's pause (%s)", lifted.get("reason"))
            self.healed = lifted
            message = "Main atak gayi thi, isliye khud restart hui. Ab phir se taiyaar hoon."
            cut = interrupted_task(self.base)
            if cut:
                message += f" '{str(cut.get('goal', ''))[:60]}' beech mein ruk gaya tha; chahiye to dobara bolo."
            self.hud_state["message"] = message
            if Path(self.base).resolve() == Path(PROJECT_ROOT).resolve():
                self._speak(message)
        thread = threading.Thread(target=run, name="chutku-heal", daemon=True)
        thread.start()
        return thread

    # -- agent sessions ---------------------------------------------------------
    def planners(self, choice=None):
        """(lead planner, fallback). H9 choice for one request: "local" = only the local models (4B, then 8B);
        "cloud" = the free cloud models lead even when the owner's default is local (never in offline mode)."""
        if self.planner_factory is not None:
            return self.planner_factory()
        from chutku.brain_service import shared_service, strong_service
        from chutku.cloud_planner import BackupPlanner, cloud_first_planner, fallback_planner
        local = LocalAgentPlanner(shared_service(self.base))
        prefs = self.preferences.load()
        if choice == "local":
            strong = strong_service(self.base)
            return local, (BackupPlanner(None, strong) if strong is not None else None)
        if (prefs.get("brain") == "cloud_first" or choice == "cloud") and not prefs.get("offline_mode"):
            # W2 (owner, 2026-10-29: "free cloud first"): Groq/Cerebras/Gemini plan; the local model takes over
            # only when they fail, and never leads while the cloud is up (cheap_second_opinion False).
            cloud = cloud_first_planner(self.base)
            if cloud is not None:
                local.cheap_second_opinion = lambda: False
                return cloud, local
        return local, fallback_planner(self.base)

    def start_agent_work(self, session, action, *, queue=True, placement=None):
        """Run agent work on a worker thread that owns the server action lock. While another order runs, a new
        one waits in line (status "queued") and starts by itself: give several orders and walk away.
        H18 placement: "later" always waits in line (never a side slot); "first" waits at the front of the line."""
        if self.action_lock.acquire(blocking=False):
            self._run_work(session, action)
            return
        if queue and placement is None and self._parallel(session, action):
            return
        if not queue:
            raise ExecutionBusy("Another action is running. Wait for it to finish.")
        with self.queue_lock:
            if len(self.work_queue) >= MAX_QUEUED:
                raise ExecutionBusy(f"{MAX_QUEUED} orders are already waiting. Let some finish first.")
            if placement == "first":
                self.work_queue.insert(0, (session, action))
            else:
                self.work_queue.append((session, action))
        with session.lock:
            session.status = "queued"
        self._next_work()  # the running order may have finished in the meantime

    def _parallel(self, session, action):
        """Y3 (2026-11-06, owner: "multiple tasks simultaneously"): while a task runs, up to MAX_PARALLEL more start
        at once on their own threads instead of waiting in line. A plain question may only observe
        (AgentSession.observe_only). Steps that change something still run one at a time (the runtime's execution
        lock; a side task's step waits for it), so two tasks never act in the same instant.
        App Mastery 2: that lock is per lane (Runtime.lane). Steps in different apps' UI Automation lanes or the headless
        browser run truly at the same time; screen, mouse and keyboard steps still take turns."""
        # shortcut: two side-by-side UI tasks can still alternate focus between their steps; add per-window
        # ownership if the owner sees keys land in the wrong window.
        from chutku.agent_loop import _ACTION_WORDS, _QUESTION
        with self.queue_lock:
            if self.parallel_running >= self.MAX_PARALLEL:
                return False
            self.parallel_running += 1
        session.observe_only = bool(_QUESTION.search(session.goal)) and not _ACTION_WORDS.search(session.goal)
        self._run_work(session, action, side=True)
        return True

    def queued_ids(self):
        with self.queue_lock:
            return [queued.id for queued, _action in self.work_queue]

    def _next_work(self):
        """Start the oldest queued order if nothing is running; announce the summary when the line is empty."""
        while True:
            with self.queue_lock:
                if not self.work_queue:
                    finished, self.batch = (self.batch, []) if not self.action_lock.locked() else (None, self.batch)
                    break
                if not self.action_lock.acquire(blocking=False):
                    return
                session, action = self.work_queue.pop(0)
            if session.status == "cancelled":  # stopped while waiting
                self.action_lock.release()
                continue
            self._run_work(session, action)
            return
        if finished and len(finished) > 1:
            self._announce_batch(finished)

    def _announce_batch(self, sessions):
        """A Windows notification when a run of several orders is over ("while you were away")."""
        done = sum(1 for item in sessions if item.status == "done")
        lines = [("✓ " if item.status == "done" else "✗ ") + item.goal[:50] for item in sessions[:6]]
        try:
            from chutku.health import notify
            notify(f"Chutku finished {done} of {len(sessions)} tasks", "\n".join(lines))
        except Exception:
            pass  # the dashboard still shows every task

    def setup_view(self):
        """What the first-run page shows. Never a key, password or token: only whether one is stored."""
        from chutku import identity, setup_wizard
        if getattr(self, "downloads", None) is None:
            from chutku.models import Downloads
            self.downloads = Downloads(self.base)
        try:   # only whether a key is stored: the page never sees one
            from chutku import cloud_planner, providers
            keys = {"groq": "groq" in providers.configured(self.base), "gemini": bool(cloud_planner.api_key())}
        except Exception:
            keys = {"groq": False, "gemini": False}
        from chutku.core.preferences import defaults as start_defaults
        prefs = self.preferences.load()
        current = identity.load(Path(self.base) / ".env")
        return {**setup_wizard.state(self.base), "assistant": {k: current.get(k) for k in
                                                                ("ASSISTANT_NAME", "ASSISTANT_GENDER",
                                                                 "ASSISTANT_LANGUAGE", "ASSISTANT_STYLE")},
                "keys_stored": keys, "mode": prefs["handsfree_mode"], "packs": self.downloads.status(),
                # what this install starts with (an installed app: Safe; the owner's checkout: Full), so the page
                # marks that choice "(recommended)" and never contradicts the preselected one
                "default_mode": start_defaults()["handsfree_mode"],
                "phone_account": current.get("CHUTKU_ACCOUNT_ID") or None,
                "permissions": setup_wizard.permissions(self.base),
                "remembered": __import__("chutku.approval_memory", fromlist=["entries"]).entries(self.base),
                "links": {"groq": "https://console.groq.com/keys", "gemini": "https://aistudio.google.com/apikey"}}

    def setup_action(self, data):
        from chutku import setup_wizard
        action = data.get("action") if isinstance(data, dict) else None
        if action not in self.SETUP_ACTIONS:
            raise ValueError("Unknown setup step.")
        if action == "assistant":
            fields = {k: data.get(k, "") for k in ("ASSISTANT_NAME", "ASSISTANT_GENDER", "ASSISTANT_LANGUAGE",
                                                   "ASSISTANT_STYLE") if data.get(k)}
            setup_wizard.set_assistant(self.base, fields)
        elif action == "name":
            setup_wizard.set_owner_name(self.base, data.get("name", ""))
        elif action == "key":
            setup_wizard.store_brain_key(self.base, data.get("provider"), data.get("key"))
        elif action == "mic":
            return {"microphone": setup_wizard.mic_level(self.base), **self.setup_view()}
        elif action == "mode":
            if data.get("mode") not in setup_wizard.AUTONOMY:
                raise ValueError("Choose safe, edits or full.")
            setup_wizard.set_autonomy(self.base, data["mode"])
        elif action == "download":
            self.setup_view()   # creates the downloader
            self.downloads.start(data.get("pack"))
            setup_wizard._mark(self.base, "packs")
        elif action == "phone":
            setup_wizard.link_phone(self.base, data.get("relay", ""), data.get("id", ""), data.get("password", ""),
                                    data.get("pin", ""), new=data.get("new") is True)
        elif action == "browser_login":
            from chutku.tools import signed_in_browser
            signed_in_browser.login()
            setup_wizard._mark(self.base, "browser")
        elif action == "forget_approval":   # WA1: Settings > "Things you let Chutku do without asking"
            from chutku import approval_memory
            approval_memory.forget(self.base, data.get("id"))
        elif action == "permission":   # Settings > "What Chutku may do"
            setup_wizard.set_permission(self.base, data.get("capability"), data.get("on"))
        elif action == "finish":   # owner 2026-11-08: no skipping past the AI key, or Chutku looks broken
            if not setup_wizard.has_brain_key(self.base):
                raise ValueError("Add your free AI key first (step 1): Chutku needs it to understand you.")
            setup_wizard.finish(self.base)
        elif action == "reopen":   # Settings > "Run setup again"
            setup_wizard._mark(self.base, done=False)
        return self.setup_view()

    # -- W6: the Automations tab (H23 blueprints) -----------------------------------------------------------------
    def automations_view(self):
        from chutku import blueprints, scheduled
        catalog = [{"name": name, "about": item["about"], "every": "daily" if item["every"] == blueprints.DAY
                    else "weekly", "slots": item["slots"]} for name, item in blueprints.CATALOG.items()]
        active = [{"id": job["id"], "goal": job["goal"], "summary": scheduled.describe(job),
                   "every_minutes": job.get("every_minutes")} for job in scheduled.active(self.base)]
        return {"catalog": catalog, "active": active}

    def board_action(self, data):
        """The Board tab's buttons: done / again / archive one task (owner clicks; nothing is ever deleted)."""
        from chutku import board
        if set(data) != {"action", "id"} or type(data.get("id")) is not int or data["action"] not in {
                "done", "again", "archive"}:
            raise ValueError("Give action done, again or archive, and the task id.")
        task = board.get(self.base, data["id"])
        if data["action"] == "again":
            board.retry(self.base, task["id"])
        else:
            board.set_status(self.base, task["id"], "done" if data["action"] == "done" else "archived")
        return self.board_view(include_done=True)

    def board_view(self, include_done=False):
        """H15: the board for the dashboard (open tasks; with include_done also finished ones) and running workers."""
        from chutku import board
        try:
            rows = board.tasks(self.base)
        except (OSError, ValueError) as error:
            return {"tasks": [], "running": [], "error": str(error)}
        if not include_done:
            rows = [t for t in rows if t["status"] != "done"]
        running = sorted(self.board.running) if self.board is not None else []
        return {"tasks": rows[-30:], "running": running}

    def start_board(self):
        """H15: run research tasks beside normal work; respects the owner's pause (H2)."""
        from chutku import board, pause, research
        from chutku.health import notify

        def paused():
            return ActionControl(self.base).paused or pause.engaged(self.base)

        def tell(title, message):
            notify(title, message)
            from chutku.gateway import telegram
            telegram.deliver(self.base, f"{title}\n{message}", kind="research")   # H16: only if paired and handed off
        self.board = board.Dispatcher(self.base, research.dashboard_worker(self), notify=tell, paused=paused)
        self.board.start(self.closing)
        return self.board

    def trust_session(self, session_id):
        """The owner said "don't ask again" while approving: the rest of this one task runs as trusted (only very
        risky steps still ask). A task in review mode stays in review."""
        session = self.agent_sessions.get(session_id)
        with session.lock:
            if session.mode != AutonomyMode.REVIEW:
                session.mode = AutonomyMode.TRUSTED.value
        return session.mode

    def run_nightshift(self):
        """Start the nightly jobs on a background thread (one at a time); the report lands in data/nightshift/."""
        if getattr(self, "_nightshift", None) is not None and self._nightshift.is_alive():
            return {"started": False, "reason": "Night Shift is already running."}

        def work():
            from chutku import nightshift
            try:
                planner = self.planners()[0] if self.planner_factory is None else None
                nightshift.run_once(self.base, model=planner)
            except Exception:
                _log().exception("night shift failed")
        self._nightshift = threading.Thread(target=work, name="chutku-nightshift", daemon=True)
        self._nightshift.start()
        return {"started": True}

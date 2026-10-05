import time
import unittest
from pathlib import Path

from chutku.agent_loop import validate_proposal
from tests import test_dashboard as _harness


def proposal(status="continue", steps=(), reply=""):
    return {"status": status, "reply": reply, "declared_plan": ["do it"],
            "next_steps": [{"tool": t, "arguments": a, "purpose": "p"} for t, a in steps]}


class Scripted:
    name = "scripted"

    def __init__(self, *items):
        self.items = list(items)

    def propose(self, session, runtime, check=None):
        raw = self.items.pop(0) if self.items else proposal("done", reply="finished")
        return validate_proposal(raw, runtime, {t.name for t in runtime.registry.list()}), {
            "planner": self.name, "seconds": 0, "backend": "test"}


class DashboardAgentTests(unittest.TestCase):
    # Reuse only the server harness, not the base class's tests.
    _base = _harness.DashboardTests
    setUp, request = _base.setUp, _base.request

    def tearDown(self):
        # Let a background agent worker release its databases before cleanup.
        if self.server.action_lock.acquire(timeout=10):
            self.server.action_lock.release()
        self._base.tearDown(self)

    def script(self, *items):
        planner = Scripted(*items)
        self.server.planner_factory = lambda: (planner, None)

    def wait(self, session_id, until=("done", "clarify", "failed", "stopped", "cancelled", "waiting_confirmation")):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status, body, _ = self.request("/api/agent/session?id=" + session_id)
            self.assertEqual(status, 200, body)
            if body["session"]["status"] in until:
                return body["session"]
            time.sleep(0.05)
        self.fail("session did not settle")

    def test_exact_command_uses_instant_deterministic_path(self):
        status, body, _ = self.request("/api/chat", {"message": "what time is it", "mode": "auto_safe"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kind"], "direct")
        self.assertEqual(body["result"]["state"], "COMPLETED")

    def test_catalog_file_phrases_go_to_the_agent_not_the_sandbox_catalog(self):
        self.script(proposal("done", reply="ok"))
        _, body, _ = self.request("/api/chat", {"message": "find report in documents", "mode": "auto_safe"})
        self.assertEqual(body["kind"], "agent")
        self.wait(body["session"]["id"])

    def test_free_form_goal_runs_agent_loop_to_done(self):
        self.script(proposal(steps=[("system.get_time", {})]), proposal("done", reply="It is noon."))
        status, body, _ = self.request("/api/chat", {"message": "tell me roughly what time it is please",
                                                     "mode": "auto_safe"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["kind"], "agent")
        session = self.wait(body["session"]["id"])
        self.assertEqual(session["status"], "done")
        self.assertEqual([s["tool"] for s in session["steps"]], ["system.get_time"])
        self.assertIn("It is noon.", session["reply"])

    def test_confirmation_flow_and_cancel_has_no_effect(self):
        target = self.base / "sandbox" / "agent-note.txt"
        self.script(proposal(steps=[("filesystem.write_text", {"path": "agent-note.txt", "content": "hi"})]))
        _, body, _ = self.request("/api/chat", {"message": "please save hi into a note for me", "mode": "auto_safe"})
        session = self.wait(body["session"]["id"])
        self.assertEqual(session["status"], "waiting_confirmation")
        self.assertFalse(target.exists())
        status, body, _ = self.request("/api/agent/confirm", {"id": session["id"], "approve": False})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.wait(session["id"])["status"], "cancelled")
        self.assertFalse(target.exists())

    def test_confirmation_approve_runs_exact_step(self):
        target = self.base / "sandbox" / "agent-note.txt"
        self.script(proposal(steps=[("filesystem.write_text", {"path": "agent-note.txt", "content": "hi"})]),
                    proposal("done", reply="saved"))
        _, body, _ = self.request("/api/chat", {"message": "please save hi into a note for me", "mode": "review"})
        session = self.wait(body["session"]["id"])
        self.assertEqual(session["status"], "waiting_confirmation")
        self.request("/api/agent/confirm", {"id": session["id"], "approve": True})
        self.assertEqual(self.wait(session["id"], until=("done", "failed", "clarify"))["status"], "done")
        self.assertEqual(target.read_text(encoding="utf-8"), "hi")

    def test_invalid_mode_and_unknown_session_rejected(self):
        status, _, _ = self.request("/api/chat", {"message": "do something useful", "mode": "yolo"})
        self.assertEqual(status, 400)
        status, _, _ = self.request("/api/agent/session?id=nope")
        self.assertEqual(status, 404)
        status, _, _ = self.request("/api/agent/confirm", {"id": "nope", "approve": True})
        self.assertEqual(status, 400)

    def test_agent_endpoints_require_session_token(self):
        status, _, _ = self.request("/api/chat", {"message": "open calculator please", "mode": "auto_safe"},
                                    headers={"X-Chutku-Token": "wrong"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()


class HudFeedTests(unittest.TestCase):
    _base = DashboardAgentTests._base
    setUp, request, tearDown = DashboardAgentTests.setUp, DashboardAgentTests.request, DashboardAgentTests.tearDown
    script, wait = DashboardAgentTests.script, DashboardAgentTests.wait

    def test_hud_follows_the_session_and_shows_pause(self):
        from chutku.core.action_control import ActionControl
        self.assertEqual(self.server.hud_status()["phase"], "idle")
        self.script(proposal(steps=[("system.get_time", {})]), proposal("done", reply="It is noon."))
        self.server.hud_submit("tell me the time please now")
        session_id = self.server.hud_state["session_id"]
        self.wait(session_id, until=("done",))
        state = self.server.hud_status()
        self.assertEqual(state["phase"], "done")
        self.assertIn("noon", state["session"]["reply"])
        self.assertFalse(state["paused"])
        ActionControl(self.server.base).pause()
        self.assertTrue(self.server.hud_status()["paused"])
        ActionControl(self.server.base).resume()

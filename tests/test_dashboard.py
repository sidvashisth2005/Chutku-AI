import http.client
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.brain import validate_tool_plan
from chutku.dashboard import DashboardServer


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.server = DashboardServer(self.base, port=0)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = {"X-Chutku-Token": self.server.token, "Origin": self.server.origin}
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        connection.request("POST" if data is not None else "GET", path,
                           json.dumps(data) if data is not None else None, request_headers)
        response = connection.getresponse()
        body = response.read()
        result = (response.status, json.loads(body) if response.getheader("Content-Type", "").startswith("application/json") else body,
                  dict(response.getheaders()))
        connection.close()
        return result

    def tool_plan(self, steps):
        with create_runtime(self.base) as runtime:
            return validate_tool_plan({"reply": "Prepared.", "steps": steps,
                                       "needs_clarification": False}, runtime)

    def test_static_ui_has_no_embedded_session_secret_and_sets_security_headers(self):
        status, body, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"What should I do?", body)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("/app.js")[0], 200)
        self.assertEqual(self.request("/style.css")[0], 200)

    def test_requests_reuse_pool_threads_instead_of_starting_one_each(self):
        """Hang dumps 2026-11-05..09: the HTTP loop sat in Thread.start for 8 s; 116k threads had been started."""
        for _ in range(3):
            self.assertEqual(self.request("/style.css")[0], 200)
        started = []
        real_start = threading.Thread.start
        with patch.object(threading.Thread, "start", lambda t: (started.append(t.name), real_start(t))[1]):
            for _ in range(25):
                self.assertEqual(self.request("/style.css")[0], 200)
        self.assertLessEqual(len(started), 4, started)       # was one new thread per request
        self.assertTrue(all(name.startswith("chutku-http") for name in started), started)

    def test_approval_http_boundary_binds_exact_task_and_rejects_tampering(self):
        from chutku.app import create_runtime
        from chutku.tools.registry import Risk, Tool, ToolResult, Verification
        effects = []
        def factory(base):
            runtime = create_runtime(base)
            runtime.registry._tools["system.get_time"] = Tool("system.get_time", "Fixture", Risk.EXTERNAL_SIDE_EFFECT,
                lambda args, ctx: (effects.append("executed") or ToolResult({}, Verification.PASS)))
            return runtime
        with patch("chutku.dashboard.create_runtime", side_effect=factory):
            status, payload, _ = self.request("/api/command", {"message": "time"})
            self.assertEqual(status, 200)
            result = payload["result"]
            self.assertEqual(result["state"], "WAITING_CONFIRMATION")
            token = result["approval"]["token"]
            self.assertEqual(self.request("/api/approve", {"token": token, "arguments": {}})[0], 400)
            self.assertEqual(self.request("/api/approve", {"token": token}, {"X-Chutku-Token": "wrong"})[0], 403)
            self.assertFalse(effects)
            approved = self.request("/api/approve", {"token": token})[1]["result"]
            self.assertEqual(approved["state"], "COMPLETED")
            self.assertEqual(approved["task_id"], result["task_id"])
            self.assertEqual(self.request("/api/approve", {"token": token})[0], 400)
            self.assertEqual(effects, ["executed"])

    def test_sequence_review_rejects_tampering_replay_and_cancel(self):
        status, payload, _ = self.request('/api/plan/preview', {'commands': ['write reviewed to note.txt', 'read note.txt']})
        self.assertEqual(status, 200)
        target = self.base / 'sandbox/note.txt'
        self.assertFalse(target.exists())
        token = payload['preview_token']
        self.assertEqual(self.request('/api/plan/execute', {'preview_token': token, 'commands': ['time']})[0], 400)
        self.assertEqual(self.request('/api/plan/execute', {'preview_token': token})[1]['result']['state'], 'COMPLETED')
        self.assertEqual(target.read_text(), 'reviewed')
        self.assertEqual(self.request('/api/plan/execute', {'preview_token': token})[0], 400)
        token = self.request('/api/plan/preview', {'commands': ['time']})[1]['preview_token']
        self.request('/api/plan/cancel', {'preview_token': token})
        self.assertEqual(self.request('/api/plan/execute', {'preview_token': token})[0], 400)

    def test_unguarded_server_cannot_claim_emergency_stop(self):
        self.assertFalse(self.request("/api/state")[1]["guard_active"])
        self.assertEqual(self.request("/api/control", {"action": "stop"})[0], 409)

    def test_brain_preview_requires_review_and_rejects_tampering_replay_and_cancel(self):
        plan = self.tool_plan([{"tool": "system.get_time", "arguments": {}, "purpose": "Read the current time"}])
        with patch("chutku.brain.preview_tool_plan", return_value=plan):
            status, payload, _ = self.request("/api/brain/preview", {"message": "tell me the time please"})
            self.assertEqual(status, 200)
            self.assertEqual(self.request("/api/state")[1]["history"], [])
            token = payload["preview_token"]
            self.assertEqual(self.request("/api/brain/execute", {"preview_token": token, "commands": ["open calculator"]})[0], 400)
            result = self.request("/api/brain/execute", {"preview_token": token})[1]
            self.assertEqual(result["result"]["state"], "COMPLETED")
            self.assertEqual(self.request("/api/brain/execute", {"preview_token": token})[0], 400)
            _, payload, _ = self.request("/api/brain/preview", {"message": "time"})
            token = payload["preview_token"]
            self.request("/api/brain/cancel", {"preview_token": token})
            self.assertEqual(self.request("/api/brain/execute", {"preview_token": token})[0], 400)

    def test_pause_bypasses_busy_dashboard_but_requires_valid_session(self):
        self.server.action_lock.acquire()
        try:
            self.assertEqual(self.request("/api/control", {"action": "pause"}, {"X-Chutku-Token": ""})[0], 403)
            status, payload, _ = self.request("/api/control", {"action": "pause"})
            self.assertEqual(status, 200)
            self.assertTrue(payload["actions_paused"])
        finally:
            self.server.action_lock.release()
        self.assertTrue(self.request("/api/state")[1]["actions_paused"])
        result = self.request("/api/command", {"message": "create folder blocked"})[1]
        self.assertEqual(result["result"]["state"], "FAILED")
        self.assertFalse((self.base / "sandbox/blocked").exists())
        self.assertEqual(self.request("/api/control", {"action": "resume"})[0], 200)
        self.assertEqual(self.request("/api/control", {"action": []})[0], 400)

    def test_voice_cancel_bypasses_action_lock_and_is_session_bound(self):
        from chutku.voice.session import voice_session
        self.server.action_lock.acquire()
        try:
            with voice_session.active("listening"):
                status, payload, _ = self.request("/api/voice/cancel", {})
                self.assertEqual(status, 200)
                self.assertTrue(payload["capture_cancelled"])
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    voice_session.check_capture()
        finally:
            self.server.action_lock.release()
        self.assertFalse(self.request("/api/voice/cancel", {})[1]["capture_cancelled"])
        self.assertEqual(self.request("/api/voice/cancel", {"extra": True})[0], 400)

    def test_voice_review_is_server_bound_single_use_and_preserves_provenance(self):
        plan = self.tool_plan([{"tool": "system.get_time", "arguments": {}, "purpose": "Read the current time"}])
        with patch("chutku.voice.recognition.capture", return_value="audio"), patch(
                "chutku.voice.recognition.recognize", return_value={"text": "what time is it", "confidence": 0.99}), patch(
                "chutku.brain.preview_tool_plan", return_value=plan):
            status, payload, _ = self.request("/api/command", {"message": "listen for a command"})
        self.assertEqual(status, 200)
        token = payload["voice_review_token"]
        self.assertTrue(token)
        self.assertEqual(self.request("/api/voice/execute", {
            "review_token": token, "message": "open calculator"})[0], 400)
        status, executed, _ = self.request("/api/voice/execute", {"review_token": token})
        self.assertEqual(status, 200)
        self.assertEqual(executed["result"]["state"], "COMPLETED")
        self.assertEqual(executed["voice_source_task_id"], payload["result"]["task_id"])
        task_id = executed["result"]["plan_steps"][0]["task_id"]
        trace = self.request("/api/trace?id=" + task_id)[1]["events"]
        authorization = next(row for row in trace if row["event_type"] == "authorization")
        self.assertEqual(authorization["details"]["provenance"], "reviewed_microphone")
        self.assertEqual(self.request("/api/voice/execute", {"review_token": token})[0], 400)
        with patch("chutku.voice.recognition.capture", return_value="audio"), patch(
                "chutku.voice.recognition.recognize", return_value={"text": "system status", "confidence": 0.99}), patch(
                "chutku.brain.preview_tool_plan", return_value=plan):
            proposal = self.request("/api/command", {"message": "listen for a command"})[1]
        token = proposal["voice_review_token"]
        self.assertEqual(self.request("/api/voice/review/cancel", {"review_token": token})[0], 200)
        self.assertEqual(self.request("/api/voice/execute", {"review_token": token})[0], 400)

    def test_api_rejects_missing_token_foreign_origin_and_rebound_host(self):
        self.assertEqual(self.request("/api/state", headers={"X-Chutku-Token": ""})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"X-Chutku-Token": "é"})[0], 403)
        self.assertEqual(self.request("/api/command", {"message": "time"}, {"Origin": "https://attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/", headers={"Host": "attacker.invalid"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertFalse((self.base / "sandbox").exists())

    def test_wrong_content_type_and_oversized_requests_are_rejected(self):
        self.assertEqual(self.request("/api/command", {"message": "time"}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("/api/command", {"message": "x" * 131073})[0], 413)

    def test_no_file_serving_or_get_mutation_endpoint(self):
        self.assertEqual(self.request("/../data/memory.db")[0], 404)
        self.assertEqual(self.request("/api/execute")[0], 404)
        self.assertEqual(self.request("/api/command")[0], 404)

    def test_command_routes_to_runtime_and_exposes_redacted_trace(self):
        status, payload, _ = self.request("/api/command", {"message": "write private-http-value to note.txt"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["state"], "COMPLETED")
        task_id = payload["result"]["task_id"]
        _, trace, _ = self.request("/api/trace?id=" + task_id)
        self.assertNotIn("private-http-value", json.dumps(trace))
        self.assertIn("[REDACTED]", json.dumps(trace))
        self.assertEqual((self.base / "sandbox/note.txt").read_text(), "private-http-value")

    def test_preview_has_no_filesystem_effect_and_can_execute_only_once(self):
        status, payload, _ = self.request("/api/preview", {"name": "HTTP Demo"})
        self.assertEqual(status, 200)
        self.assertFalse((self.base / "sandbox/HTTP Demo").exists())
        request = {"preview_token": payload["preview_token"]}
        status, result, _ = self.request("/api/execute", request)
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["state"], "COMPLETED")
        self.assertTrue((self.base / "sandbox/HTTP Demo/README.md").is_file())
        self.assertEqual(self.request("/api/execute", request)[0], 400)

    def test_cancelled_and_expired_previews_do_not_execute(self):
        _, payload, _ = self.request("/api/preview", {"name": "Cancelled"})
        request = {"preview_token": payload["preview_token"]}
        self.assertEqual(self.request("/api/cancel", request)[0], 200)
        self.assertEqual(self.request("/api/execute", request)[0], 400)
        self.server.previews.ttl = 0
        _, expired, _ = self.request("/api/preview", {"name": "Expired"})
        self.assertEqual(self.request("/api/execute", {"preview_token": expired["preview_token"]})[0], 400)
        self.assertEqual(list((self.base / "sandbox").iterdir()), [])

    def test_preview_cannot_be_retargeted_or_self_confirmed(self):
        _, payload, _ = self.request("/api/preview", {"name": "Original"})
        self.assertEqual(self.request("/api/execute", {"preview_token": payload["preview_token"], "name": "Other"})[0], 400)
        self.assertEqual(self.request("/api/command", {"message": "time", "confirmed_on_screen": True})[0], 400)
        self.assertFalse((self.base / "sandbox/Original").exists())

    def test_preconditions_rechecked_after_preview(self):
        _, payload, _ = self.request("/api/preview", {"name": "Collision"})
        target = self.base / "sandbox/Collision"
        target.mkdir()
        (target / "README.md").write_text("user-created", encoding="utf-8")
        _, result, _ = self.request("/api/execute", {"preview_token": payload["preview_token"]})
        self.assertEqual(result["result"]["state"], "FAILED")
        self.assertEqual((target / "README.md").read_text(), "user-created")

    def test_parallel_action_is_rejected(self):
        self.server.action_lock.acquire()
        try:
            self.assertEqual(self.request("/api/command", {"message": "time"})[0], 409)
        finally:
            self.server.action_lock.release()

    def test_memory_and_history_are_available_in_state(self):
        self.request("/api/command", {"message": "remember language = English"})
        _, state, _ = self.request("/api/state")
        self.assertEqual(state["memories"][0]["value"], "English")
        self.assertEqual(state["history"][0]["tool"], "memory.remember")
        self.assertIn("apps.open", {tool["name"] for tool in state["tools"]})

    def test_traversal_command_fails_without_writing_outside_root(self):
        _, result, _ = self.request("/api/command", {"message": "write wrong to ../escape.txt"})
        self.assertEqual(result["result"]["state"], "DENIED")
        self.assertFalse((self.base / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main()

"""W2 (2026-10-29): the free cloud brain plans first, rotates on quota, and never sees private results."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import providers
from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.cloud_planner import CloudAgentPlanner


def reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj)}}]}


PLAN = {"status": "continue", "reply": "", "declared_plan": ["read the time"],
        "next_steps": [{"tool": "system.get_time", "arguments_json": "{}", "purpose": "read the clock"}],
        "finish": False}


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_quota_moves_to_the_next_rung_and_cools_down(self):
        calls = []

        def transport(url, body):
            calls.append(body["model"])
            if body["model"] == "a":
                raise providers.ProviderError("quota", kind="quota", retry_after=30)
            return reply({"ok": True})
        with patch.object(providers, "api_key", return_value="k"):
            parsed, meta = providers.ask("s", "u", base=self.base, transport=transport,
                                         rungs=[("groq", "a"), ("groq", "b")])
        self.assertEqual(parsed, {"ok": True})
        self.assertEqual((meta["provider"], meta["model"]), ("groq", "b"))
        self.assertIn("groq/a", providers.cooling(self.base))
        self.assertEqual(calls, ["a", "b"])

    def test_everything_down_raises_exhausted(self):
        def down(*a, **k):
            raise providers.ProviderError("x", kind="unavailable")
        with patch.object(providers, "chat_json", side_effect=down):
            with self.assertRaises(providers.ProviderError) as caught:
                providers.ask("s", "u", base=self.base, rungs=[("groq", "a")])
        self.assertEqual(caught.exception.kind, "exhausted")

    def test_no_key_means_no_rungs(self):
        with patch.object(providers, "api_key", return_value=None):
            self.assertEqual(providers.ladder(self.base), [])

    def test_malformed_answers_are_refused(self):
        bad = lambda url, body: {"choices": [{"message": {"content": "not json"}}]}
        with self.assertRaises(providers.ProviderError) as caught:
            providers.chat_json("groq", "m", "s", "u", key="k", transport=bad)
        self.assertEqual(caught.exception.kind, "malformed")


class CloudPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def planner(self, answer, sent):
        def transport(url, body):
            sent.append(body)
            return reply(answer)
        return CloudAgentPlanner(self.base, transport=transport, rungs=[("groq", "llama-3.3-70b-versatile")])

    def test_a_cloud_plan_passes_the_same_validation(self):
        sent = []
        with create_runtime(self.base) as runtime, patch.object(providers, "api_key", return_value="k"):
            proposal, meta = self.planner(PLAN, sent).propose(AgentSession("kitne baje hain", mode="owner"), runtime)
        self.assertEqual([s["tool"] for s in proposal["next_steps"]], ["system.get_time"])
        self.assertEqual(meta["planner"], "cloud:groq")
        self.assertEqual(sent[0]["response_format"], {"type": "json_object"})

    def test_an_invented_tool_is_refused(self):
        bad = dict(PLAN, next_steps=[{"tool": "system.format_disk", "arguments_json": "{}", "purpose": "x"}])
        with create_runtime(self.base) as runtime, patch.object(providers, "api_key", return_value="k"):
            with self.assertRaises(OSError):
                self.planner(bad, []).propose(AgentSession("do it", mode="owner"), runtime)

    def test_private_file_text_never_leaves(self):
        sent = []
        session = AgentSession("summarise my notes file", mode="owner")
        session.steps.append({"tool": "filesystem.read_text", "arguments": {"path": "notes.txt"}, "state": "COMPLETED",
                              "observation": {"text": "SECRET-BANK-PIN-4321"}, "message": "read"})
        with create_runtime(self.base) as runtime, patch.object(providers, "api_key", return_value="k"):
            self.planner(dict(PLAN, status="done", reply="ok", next_steps=[]), sent).propose(session, runtime)
        payload = json.dumps(sent)
        self.assertNotIn("SECRET-BANK-PIN-4321", payload)
        self.assertIn("summarise my notes file", payload)

    def test_falls_back_to_gemini_then_fails_loudly(self):
        class Gemini:
            name = "gemini"

            def propose(self, session, runtime, check=None):
                return {"status": "done", "reply": "from gemini", "declared_plan": [], "next_steps": []}, {"planner": "gemini"}
        down = lambda url, body: (_ for _ in ()).throw(providers.ProviderError("down"))
        with create_runtime(self.base) as runtime, patch.object(providers, "api_key", return_value="k"):
            planner = CloudAgentPlanner(self.base, transport=down, rungs=[("groq", "m")], gemini=Gemini())
            proposal, meta = planner.propose(AgentSession("hello", mode="owner"), runtime)
            self.assertEqual(meta["planner"], "gemini")
            planner = CloudAgentPlanner(self.base, transport=down, rungs=[("groq", "m")])
            with self.assertRaises(OSError):
                planner.propose(AgentSession("hello", mode="owner"), runtime)


class SelectionTests(unittest.TestCase):
    def test_cloud_leads_only_when_chosen_online_and_keyed(self):
        from chutku import cloud_planner
        with TemporaryDirectory() as temp, patch.object(cloud_planner, "gemini_planner", return_value=None):
            base = Path(temp)
            with patch.object(providers, "configured", return_value=[]):
                self.assertIsNone(cloud_planner.cloud_first_planner(base, online=lambda: True))
            with patch.object(providers, "configured", return_value=["groq"]):
                self.assertIsNone(cloud_planner.cloud_first_planner(base, online=lambda: False))
                self.assertIsInstance(cloud_planner.cloud_first_planner(base, online=lambda: True), CloudAgentPlanner)

    def test_dashboard_uses_local_when_the_owner_chose_local(self):
        from chutku.core.preferences import Preferences
        from chutku.dashboard import DashboardServer
        from chutku import cloud_planner
        with TemporaryDirectory() as temp:
            base = Path(temp)
            server = DashboardServer(base, port=0)
            try:
                fake = CloudAgentPlanner(base)
                with patch.object(cloud_planner, "cloud_first_planner", return_value=fake), \
                        patch.object(cloud_planner, "fallback_planner", return_value=None):
                    lead, backup = server.planners()
                    self.assertIs(lead, fake)
                    self.assertFalse(backup.cheap_second_opinion())   # the local model never leads while cloud is up
                    Preferences(base).update({"brain": "local"})
                    lead, _ = server.planners()
                    self.assertNotIsInstance(lead, CloudAgentPlanner)
            finally:
                server.server_close()


if __name__ == "__main__":
    unittest.main()

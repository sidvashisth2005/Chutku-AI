"""H9: the owner picks the brain for one request; offline mode refuses the cloud; failures are named."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku import brain_errors
from chutku.intents.tone import brain_choice


class ChoiceWordsTests(unittest.TestCase):
    def test_phrases(self):
        self.assertEqual(brain_choice("local se karo: aaj kya date hai"), ("local", "aaj kya date hai"))
        self.assertEqual(brain_choice("Gemini se pucho best laptop under 50000"), ("cloud", "best laptop under 50000"))
        self.assertEqual(brain_choice("aaj ka weather batao online se batao"), ("cloud", "aaj ka weather batao"))
        self.assertEqual(brain_choice("use the local model: what time is it"), ("local", "what time is it"))
        self.assertEqual(brain_choice("ask gemini: capital of peru"), ("cloud", "capital of peru"))

    def test_not_a_choice(self):
        for text in ("gemini se kya fark hai", "local se karo", "spotify kholo", "cloud storage kitna bacha hai"):
            self.assertIsNone(brain_choice(text)[0], text)


class ErrorClassTests(unittest.TestCase):
    def test_classes(self):
        from chutku.providers import ProviderError
        from chutku.gemini import GeminiUnavailable
        self.assertEqual(brain_errors.classify(ProviderError("x", kind="quota")), "rate_limited")
        self.assertEqual(brain_errors.classify(ProviderError("x", kind="auth")), "auth")
        self.assertEqual(brain_errors.classify(ProviderError("x", kind="retired")), "not_found")
        self.assertEqual(brain_errors.classify(GeminiUnavailable("bad", status=503)), "server")
        self.assertEqual(brain_errors.classify(GeminiUnavailable("API key not valid", status=400)), "auth")
        self.assertEqual(brain_errors.classify(TimeoutError()), "network")
        self.assertEqual(brain_errors.classify(OSError("llama-server exited")), "local_down")
        self.assertEqual(brain_errors.classify(OSError("CUDA error: out of memory")), "local_oom")
        self.assertEqual(brain_errors.classify("something odd"), "unknown")

    def test_a_failed_round_tells_the_owner_why(self):
        from chutku.agent_loop import AgentSession
        from chutku.providers import ProviderError
        from tests.agent_fakes import FakeRuntime

        class Broken:
            name = "cloud"

            def propose(self, *_args):
                raise ProviderError("groq quota reached.", kind="quota")
        session = AgentSession("best free pdf editor kaun sa hai", mode="owner")
        session.advance(FakeRuntime(), Broken())
        self.assertEqual(session.status, "failed")          # 2026-11-08 review: not "needs more detail"
        self.assertIn("free AI limit is used up", session.reply)
        self.assertIn("Settings", session.reply)            # what to do next, with no CLI command
        self.assertNotIn("groq quota reached", session.reply)   # the planner's own words stay in the log

    def test_no_key_text_in_the_explanation(self):
        secret = "AIzaSy" + "X" * 33
        reason = brain_errors.explain([OSError(f"HTTP 403 for key {secret}")])
        self.assertNotIn(secret, reason)


class DashboardChoiceTests(unittest.TestCase):
    def setUp(self):
        from chutku.dashboard import DashboardServer
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.server = DashboardServer(self.base, port=0)
        self.addCleanup(self.server.server_close)

    def test_local_choice_never_offers_a_cloud_planner(self):
        from chutku import cloud_planner
        from chutku.core.preferences import Preferences
        Preferences(self.base).update({"brain": "cloud_first"})
        with patch.object(cloud_planner, "cloud_first_planner", side_effect=AssertionError("cloud asked")), \
                patch("chutku.brain_service.strong_service", return_value=None):
            lead, backup = self.server.planners("local")
        self.assertEqual(type(lead).__name__, "LocalAgentPlanner")
        self.assertIsNone(backup)

    def test_cloud_choice_leads_with_the_cloud_even_when_local_is_the_default(self):
        from chutku import cloud_planner
        from chutku.cloud_planner import CloudAgentPlanner
        fake = CloudAgentPlanner(self.base)
        with patch.object(cloud_planner, "cloud_first_planner", return_value=fake):
            lead, _ = self.server.planners("cloud")
        self.assertIs(lead, fake)

    def test_offline_mode_refuses_a_cloud_request(self):
        from chutku.core.preferences import Preferences
        Preferences(self.base).update({"offline_mode": True})
        session = self.server.begin_session("gemini se pucho aaj ki news", "owner", "text")
        self.assertEqual(session.status, "clarify")
        self.assertIn("Offline mode on hai", session.reply)
        self.assertEqual(session.steps, [])


if __name__ == "__main__":
    unittest.main()

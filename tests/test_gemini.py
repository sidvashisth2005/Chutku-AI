import json
import os
import unittest
from unittest.mock import patch

from chutku.ensemble import reconcile_plans
from chutku.gemini import GeminiAdvisor, GeminiUnavailable, configured
from chutku.brain import preview_dual_plan


class _Response:
    def __init__(self, value):
        self.value = value
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, limit):
        return self.value[:limit]


class GeminiTests(unittest.TestCase):
    def test_absent_key_is_an_explicit_local_fallback_condition(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(configured())
            with self.assertRaises(GeminiUnavailable):
                GeminiAdvisor()

    def test_cloud_call_requires_explicit_consent_before_network(self):
        with patch("urllib.request.urlopen") as send:
            with self.assertRaises(PermissionError):
                GeminiAdvisor(api_key="secret").plan("tell me the time", system="json",
                                                       schema={"type": "object"})
            send.assert_not_called()

    def test_fixed_endpoint_key_header_and_structured_response(self):
        plan = {"reply": "Prepared.", "commands": ["what time is it"], "needs_clarification": False}
        body = json.dumps({"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": json.dumps(plan)}]}}], "modelVersion": "gemini-test",
            "usageMetadata": {"totalTokenCount": 12}}).encode()
        with patch("urllib.request.urlopen", return_value=_Response(body)) as send:
            result = GeminiAdvisor(api_key="secret", model="gemini-3.8-flash").plan(
                "tell me the time", system="Return JSON", schema={"type": "object"}, cloud_consent=True)
        request = send.call_args.args[0]
        self.assertEqual(request.full_url,
                         "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent")
        self.assertEqual(request.headers["X-goog-api-key"], "secret")
        self.assertEqual(result["plan"], plan)
        self.assertNotIn("secret", request.data.decode())

    def test_invalid_or_oversized_cloud_output_fails_closed(self):
        for body in (b"{}", b"x" * 65537):
            with self.subTest(size=len(body)), patch("urllib.request.urlopen", return_value=_Response(body)):
                with self.assertRaises(GeminiUnavailable):
                    GeminiAdvisor(api_key="secret").plan("hello", system="json",
                        schema={"type": "object"}, cloud_consent=True)

    def test_exact_agreement_is_selected_and_disagreement_clarifies(self):
        local = {"reply": "local", "commands": ["what time is it"], "needs_clarification": False,
                 "model": "local", "inference_seconds": 1.0, "usage": {}, "experimental": True,
                 "router": "local_llm"}
        agreed = reconcile_plans(local, {"reply": "cloud", "commands": ["what time is it"],
                                        "needs_clarification": False})
        self.assertEqual(agreed["commands"], ["what time is it"])
        self.assertEqual(agreed["consultation"]["decision"], "consensus")
        refused = reconcile_plans(local, {"reply": "cloud", "commands": ["system status"],
                                         "needs_clarification": False})
        self.assertEqual(refused["commands"], [])
        self.assertTrue(refused["needs_clarification"])
        self.assertEqual(refused["router"], "dual_model_disagreement")

    def test_dual_preview_requires_consent_before_starting_either_model(self):
        with patch("chutku.brain.LocalBrain") as local:
            with self.assertRaises(PermissionError):
                preview_dual_plan("tell me the time", object())
            local.assert_not_called()

    def test_dual_preview_falls_back_when_gemini_is_not_configured(self):
        local_plan = {"reply": "local", "commands": ["what time is it"],
                      "needs_clarification": False, "model": "local", "router": "local_llm"}
        class Lock:
            def __enter__(self): return self
            def __exit__(self, *_): return False
        class Runtime:
            execution_lock = Lock()
            class action_control:
                base = "."
        with patch("chutku.brain.LocalBrain") as local, patch.dict(os.environ, {}, clear=True):
            local.return_value.__enter__.return_value.plan.return_value = local_plan
            result = preview_dual_plan("tell me the time", Runtime(), cloud_consent=True)
        self.assertEqual(result["commands"], ["what time is it"])
        self.assertEqual(result["consultation"]["decision"], "local_fallback")


if __name__ == "__main__":
    unittest.main()

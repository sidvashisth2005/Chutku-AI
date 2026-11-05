import json
import os
import unittest
from unittest.mock import patch

from chutku.gemini import GeminiAdvisor, GeminiUnavailable, configured


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


if __name__ == "__main__":
    unittest.main()

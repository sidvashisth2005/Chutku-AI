"""Release review 2026-11-07: the bot token is in every Telegram URL, so no error may carry a URL."""
import io
import unittest
import urllib.error
from unittest import mock

from chutku.gateway import telegram

TOKEN = "123456:SECRET-token-value"


class TokenNeverLeaksTests(unittest.TestCase):
    def failures(self):
        url = f"{telegram.API}/bot{TOKEN}/getUpdates"
        return [urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b"")),
                urllib.error.URLError(f"cannot reach {url}"), TimeoutError(url), OSError(url), ValueError(url)]

    def test_api_calls_and_downloads_raise_without_the_token(self):
        call = telegram._real_transport(TOKEN)
        for failure in self.failures():
            for attempt in (lambda: call("getUpdates", {}, 1), lambda: call.download("voice/file.oga", 1)):
                with self.subTest(failure=type(failure).__name__), \
                        mock.patch("urllib.request.urlopen", side_effect=failure):
                    with self.assertRaises(telegram.TelegramError) as caught:
                        attempt()
                    self.assertNotIn(TOKEN, str(caught.exception))
                    self.assertIsNone(caught.exception.__cause__)
                    self.assertTrue(caught.exception.__suppress_context__)


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from chutku.quick_intents import QUICK_ANSWERS, quick_proposal
from chutku.tools import net_check


class NetCheckTests(unittest.TestCase):
    def test_verdicts_in_plain_words(self):
        with patch("chutku.tools.net_check._local_ip", return_value=None):
            self.assertIn("No network connection", net_check.diagnose(public_ip=False)["verdict"])
        with patch("chutku.tools.net_check._local_ip", return_value="169.254.1.2"):
            self.assertIn("No network connection", net_check.diagnose(public_ip=False)["verdict"])
        with patch("chutku.tools.net_check._local_ip", return_value="192.168.1.5"), \
                patch("chutku.tools.net_check.socket.getaddrinfo", side_effect=OSError("dns")):
            self.assertIn("DNS", net_check.diagnose(public_ip=False)["verdict"])
        with patch("chutku.tools.net_check._local_ip", return_value="192.168.1.5"), \
                patch("chutku.tools.net_check.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("1.2.3.4", 443))]), \
                patch("chutku.tools.net_check._fetch", side_effect=OSError("down")):
            result = net_check.diagnose(public_ip=False)
        self.assertIn("isn't reachable", result["verdict"])
        self.assertFalse(result["online"])

    def test_ping_host_is_validated(self):
        for bad in ("bad;host", "a b", "-flag", "x" * 300, "", "google.com && calc"):
            with self.assertRaises(ValueError, msg=bad):
                net_check._validate_ping({"host": bad})
        for good in ("google.com", "8.8.8.8", "my-router.local"):
            net_check._validate_ping({"host": good})

    def test_phrases_and_answers(self):
        for text in ("is my internet working", "internet chal raha hai kya", "net slow hai", "whats my ip",
                     "mera ip kya hai"):
            self.assertEqual(quick_proposal(text, apps=[])["next_steps"][0]["tool"], "net.check", text)
        step = quick_proposal("ping google", apps=[])["next_steps"][0]
        self.assertEqual((step["tool"], step["arguments"]), ("net.ping", {"host": "google.com"}))
        self.assertIsNone(quick_proposal("ping bad;host", apps=[]))
        said = QUICK_ANSWERS["net.ping"]({"host": "x.com", "sent": 4, "received": 0, "average_ms": None,
                                           "unknown_host": False})
        self.assertIn("didn't answer", said)


if __name__ == "__main__":
    unittest.main()

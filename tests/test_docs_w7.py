"""W7: the in-app Help serves the user guide; the public docs carry no personal details; the licence notes."""
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
PERSONAL = re.compile(r"D:\\Project|Siddhant|\bAK\b|mammi|Pita Shri|RTX 3050|ChutkuScratch|\bbaki\b|Dubey|@gmail",
                      re.I)


class DocsTests(unittest.TestCase):
    def test_help_serves_the_guide_without_the_session_token(self):
        import http.client
        from test_setup_page_w5 import Server
        with TemporaryDirectory() as temp:
            web = Server(temp)
            try:
                connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=10)
                connection.request("GET", "/help", headers={"Host": f"127.0.0.1:{web.port}"})
                response = connection.getresponse()
                body = response.read().decode("utf-8")
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertIn("<h1>Chutku: User Guide</h1>", body)   # 2026-11-08: a page, not raw Markdown
                self.assertIn("text/html", response.getheader("Content-Type"))
                self.assertNotIn("**", body)
                self.assertNotIn("|---", body)
                connection = http.client.HTTPConnection("127.0.0.1", web.port, timeout=10)
                connection.request("GET", "/help", headers={"Host": "evil.example"})   # DNS rebinding: refused
                self.assertEqual(connection.getresponse().status, 403)
                connection.close()
            finally:
                web.close()
        self.assertIn('href="/help"', (ROOT / "chutku" / "web" / "index.html").read_text(encoding="utf-8"))

    def test_public_docs_have_no_personal_details(self):
        for name in ("docs/USER_GUIDE.md", "installer/README_PUBLIC.md", "README.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIsNone(PERSONAL.search(text), (name, PERSONAL.search(text)))
        self.assertIsNotNone(PERSONAL.search((ROOT / "docs" / "OWNER_GUIDE.md").read_text(encoding="utf-8")))  # the check bites

    def test_licence_notes(self):
        ledger = (ROOT / "THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8")
        for needle in ("CC BY-NC-SA 4.0", "GPL-3.0-or-later", "github.com/espeak-ng/espeak-ng", "cryptography",
                       "excluded from the app package"):
            self.assertIn(needle, ledger)
        self.assertIn("More info", (ROOT / "installer" / "README_PUBLIC.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

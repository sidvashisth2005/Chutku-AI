import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.agent_loop import TAINTING_TOOLS
from chutku.app import create_runtime
from chutku.tools import internet

DDG = """<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa&amp;rut=1" class='result-link'>Example <b>A</b></a>
<td class='result-snippet'>First snippet</td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb" class='result-link'>Example B</a>
<td class='result-snippet'>Second</td>"""
RSS = """<rss><channel><item><title>Headline one</title><source>Paper</source><pubDate>Wed</pubDate><link>https://n/1</link></item>
<item><title>Headline two</title><source>Site</source><pubDate>Wed</pubDate><link>https://n/2</link></item></channel></rss>"""


class InternetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("internet.read")

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_private_and_local_targets_refused(self):
        for url in ("http://127.0.0.1:8765/api/state", "http://localhost/", "http://10.0.0.5/", "http://[::1]/",
                    "http://169.254.169.254/latest/meta-data"):
            with self.assertRaises(internet.Blocked, msg=url):
                internet.check_public_url(url)
        with self.assertRaises(ValueError):
            internet.check_public_url("file:///C:/Windows/win.ini")

    def test_redirect_to_private_address_refused(self):
        handler = internet._SafeRedirects()
        request = type("R", (), {"full_url": "https://example.org/"})()
        with self.assertRaises(internet.Blocked):
            handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1:8765/api/state")

    def test_results_parse_and_unwrap_links(self):
        with patch.object(internet, "fetch", return_value=(DDG, "u")):
            result = self.runtime.run("web.results", {"query": "example"})
        self.assertEqual([r["url"] for r in result["output"]["results"]], ["https://example.org/a", "https://example.org/b"])
        self.assertEqual(result["output"]["results"][0]["title"], "Example A")

    def test_news_parse(self):
        with patch.object(internet, "fetch", return_value=(RSS, "u")):
            result = self.runtime.run("web.news", {"topic": "x", "count": 1})
        self.assertEqual(result["output"]["headlines"], [{"title": "Headline one", "source": "Paper",
                                                          "published": "Wed", "url": "https://n/1"}])

    def test_page_text_strips_scripts_and_takes_page_title(self):
        html = "<html><head><title>Real</title><script>evil()</script></head><body><svg><title>icon</title></svg>" \
               "<p>Hello</p><p>World</p></body></html>"
        title, text = internet.html_to_text(html)
        self.assertEqual(title, "Real")
        self.assertEqual(text, "Hello\nWorld")

    def test_weather_uses_saved_city_and_asks_otherwise(self):
        result = self.runtime.run("web.weather", {})
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("Which city", result["output"]["error"])
        self.runtime.memory.save("city", "Pune")
        calls = []

        def fake(url, **_):
            calls.append(url)
            if "geocoding" in url:
                return ('{"results":[{"name":"Pune","latitude":18.5,"longitude":73.8,"country":"India"}]}', url)
            return ('{"current":{"temperature_2m":25,"weather_code":0},"daily":{"time":["d"],"temperature_2m_max":[30],'
                    '"temperature_2m_min":[20],"precipitation_probability_max":[10],"weather_code":[1]}}', url)
        with patch.object(internet, "fetch", side_effect=fake):
            result = self.runtime.run("web.weather", {})
        self.assertEqual(str(result["state"]), "COMPLETED")
        self.assertIn("name=Pune", calls[0])
        self.assertEqual(result["output"]["now"]["sky"], "clear sky")

    def test_capability_required_and_content_taints(self):
        self.runtime.capability_grants.revoke("internet.read")
        self.assertEqual(str(self.runtime.run("web.news", {})["state"]), "DENIED")
        self.assertTrue({"web.read", "web.results", "web.news"} <= TAINTING_TOOLS)
        self.assertTrue(self.runtime.registry.get("web.read").network_egress)


if __name__ == "__main__":
    unittest.main()

"""App docs harvest (App Mastery A0): pages become clean text with an index; failures are recorded, not fatal;
every app has sources; every feature map exists, cites its sources and uses only the four risk classes."""
import json
from pathlib import Path
import re
import tempfile
import unittest
from urllib.error import HTTPError

from scripts import app_docs

ROOT = Path(__file__).resolve().parents[1]
APPS = ("spotify", "whatsapp", "brave", "vscode", "settings", "chatgpt", "discord", "vlc", "telegram", "explorer",
        "notepad")
PAGE = ("<html><head><title>Spotify keyboard shortcuts</title><script>var x = 'Ctrl+Hidden';</script></head><body>"
        "<nav>menu</nav><h1>Shortcuts</h1><table><tr><td>Play/Pause</td><td>Space</td></tr>"
        "<tr><td>Next track</td><td>Ctrl + &rarr;</td></tr></table>" + "<p>filler text line</p>" * 40 +
        "</body></html>")


class HarvestTests(unittest.TestCase):
    def test_page_text_keeps_content_and_drops_scripts(self):
        title, text = app_docs.page_text(PAGE)
        self.assertEqual(title, "Spotify keyboard shortcuts")
        self.assertIn("| Play/Pause | Space", text)
        self.assertIn("Ctrl + →", text)
        self.assertNotIn("Hidden", text)
        self.assertNotIn("menu", text)

    def test_harvest_saves_pages_and_records_failures(self):
        def fetcher(url):
            if "blocked" in url:
                raise HTTPError(url, 403, "Forbidden", None, None)
            if "empty" in url:
                return "<html><body><script>app()</script></body></html>"
            return PAGE
        with tempfile.TemporaryDirectory() as temp:
            index = app_docs.harvest("spotify", [("official", "https://ok.example/a"),
                                                 ("official", "https://blocked.example/b"),
                                                 ("reference", "https://empty.example/c")],
                                     base=Path(temp), fetcher=fetcher)
            folder = Path(temp) / "data" / "apps" / "spotify" / "sources"
            saved = json.loads((folder / "index.json").read_text(encoding="utf-8"))
            self.assertTrue((folder / "1.txt").read_text(encoding="utf-8").startswith("Spotify keyboard shortcuts"))
            self.assertFalse((folder / "2.txt").exists())
        self.assertEqual(saved, index)
        self.assertIn("sha256", index[0])
        self.assertIn("403", index[1]["error"])
        self.assertIn("almost no readable text", index[2]["error"])

    def test_every_app_has_an_official_or_reference_source(self):
        self.assertEqual(set(app_docs.SOURCES), set(APPS))
        for app, sources in app_docs.SOURCES.items():
            self.assertGreaterEqual(len(sources), 2, app)
            self.assertTrue(all(kind in {"official", "reference"} and url.startswith("https://")
                                for kind, url in sources), app)


class FeatureMapTests(unittest.TestCase):
    def test_every_map_exists_cites_sources_and_has_a_catalogue(self):
        for app in APPS:
            text = (ROOT / "docs" / "apps" / f"{app}.md").read_text(encoding="utf-8")
            self.assertIn("## Action catalogue", text, app)
            self.assertRegex(text, r"\]\(https://", app)              # cites at least one source link
            self.assertIn(f"data/apps/{app}/sources/", text, app)
            catalogue = text.split("## Action catalogue", 1)[1]
            risks = re.findall(r"\|\s*\*{0,2}(safe|changes|consequential|destructive|runs code|consequential-lite)",
                               catalogue)
            self.assertGreaterEqual(len(risks), 8, app)

    def test_destructive_actions_always_ask(self):
        for app in APPS:
            catalogue = (ROOT / "docs" / "apps" / f"{app}.md").read_text(encoding="utf-8").split(
                "## Action catalogue", 1)[1]
            for line in catalogue.splitlines():
                if line.startswith("| ") and "destructive" in line:   # catalogue rows, not the legend
                    self.assertIn("asks", line, f"{app}: {line}")


if __name__ == "__main__":
    unittest.main()

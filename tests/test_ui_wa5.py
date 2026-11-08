"""WA5: the toddler-easy page. Static checks plus the served examples; the browser run is in IMPLEMENTATION_STATUS."""
import json
import re
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from scripts import make_task_bank

WEB = Path(__file__).resolve().parents[1] / "chutku" / "web"


class ToddlerUiTests(unittest.TestCase):
    def test_say_examples_come_from_the_train_split_and_never_include_damage(self):
        rows = make_task_bank.generate()
        served = json.loads((WEB / "say.json").read_text(encoding="utf-8"))
        self.assertEqual(served, make_task_bank.examples(rows))   # regenerated with the bank
        train = {r["say"] for r in rows if r["split"] == "train" and r["category"] != "damage"}
        lines = [say for entry in served.values() for say in entry["say"]]
        self.assertTrue(lines and set(lines) <= train)              # never a held-out item or a damage request
        self.assertNotIn("damage", served)

    def test_the_dashboard_serves_the_examples_without_the_session_token(self):
        from chutku.dashboard import DashboardServer
        with tempfile.TemporaryDirectory() as folder:
            server = DashboardServer(Path(folder), port=0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/say.json", timeout=5) as reply:
                    self.assertIn("apps", json.loads(reply.read()))
            finally:
                server.shutdown()
                server.server_close()

    def test_simple_view_keeps_every_existing_tab_id(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        tabs = set(re.findall(r'data-tab="(\w+)"', html))
        for tab in ("home", "history", "memory", "mind", "board", "automations", "phone", "skills", "reliability",
                    "capabilities", "verification", "voicelock", "settings", "say"):
            self.assertIn(tab, tabs)
            self.assertIn(f'id="{tab}"', html)
        for element in ("nav-more", "say-search", "say-list", "coach-tip", "error-action", "error-banner", "chat-input"):
            self.assertIn(f'id="{element}"', html)
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('new Set(["home","history","phone","settings","say"])', app)
        self.assertIn('try{localStorage.setItem("chutku-view"', app)   # the choice is remembered, safely


if __name__ == "__main__":
    unittest.main()

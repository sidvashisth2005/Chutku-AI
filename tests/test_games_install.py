import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.tools import apps_extra

SEARCH = {"total": 3, "items": [{"id": 1030300, "name": "Hollow Knight: Silksong"}, {"id": 367520, "name": "Hollow Knight"},
                                {"id": 5, "name": "Hollow Knight - Official Soundtrack"}]}


class GamesInstallTests(unittest.TestCase):
    def test_lookup_prefers_exact_name(self):
        fetch = lambda url, accept=None: (json.dumps(SEARCH), url)
        self.assertEqual(apps_extra.steam_lookup("hollow knight", fetch=fetch)["id"], 367520)
        self.assertEqual(apps_extra.steam_lookup("silk", fetch=fetch)["id"], 1030300)  # top hit when nothing exact
        self.assertIsNone(apps_extra.steam_lookup("zzz", fetch=lambda url, accept=None: ('{"items": []}', url)))

    def test_opens_steam_install_window_or_reports_installed(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("apps.launch")
            opened = []
            with patch("chutku.tools.apps_extra.steam_games", return_value=[]), \
                    patch("chutku.tools.apps_extra.epic_games", return_value=[]), \
                    patch("chutku.tools.apps_extra.steam_lookup",
                          return_value={"id": 367520, "name": "Hollow Knight", "others": []}), \
                    patch("chutku.tools.apps_extra.os.startfile", side_effect=opened.append), \
                    patch("chutku.tools.apps_extra.time.sleep"):
                result = runtime.run("games.install", {"name": "hollow knight"})
            self.assertEqual(opened, ["steam://install/367520"])
            self.assertEqual(result["output"]["game"], "Hollow Knight")
            with patch("chutku.tools.apps_extra.steam_games", return_value=[{"name": "Hollow Knight", "store": "Steam"}]), \
                    patch("chutku.tools.apps_extra.epic_games", return_value=[]), \
                    patch("chutku.tools.apps_extra.os.startfile") as start:
                installed = runtime.run("games.install", {"name": "Hollow Knight"})
                start.assert_not_called()
            self.assertTrue(installed["output"]["already_installed"])

    def test_needs_launch_permission(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            self.assertEqual(runtime.run("games.install", {"name": "x"})["state"], "DENIED")


if __name__ == "__main__":
    unittest.main()

"""Network, paths and the action log fail closed (master plan S3)."""
import json
import os
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.core import paths
from chutku.policy.kernel import Decision
from chutku.tools import documents, internet
from chutku.tools.registry import ExecutionContext, Risk, Tool, ToolResult, Verification


def _addresses(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


class NetworkTests(unittest.TestCase):
    def test_pinned_connection_rechecks_the_address_it_connects_to(self):
        connection = internet._PinnedHTTPSConnection("rebind.example", 443, timeout=2)
        with patch.object(internet.socket, "getaddrinfo", return_value=_addresses("127.0.0.1")), \
                patch.object(internet.socket, "create_connection") as connect:
            with self.assertRaises(internet.Blocked):
                connection.connect()
        connect.assert_not_called()

    def test_public_address_must_all_be_public(self):
        with patch.object(internet.socket, "getaddrinfo", return_value=_addresses("93.184.216.34", "10.0.0.5")):
            with self.assertRaises(internet.Blocked):
                internet.public_address("mixed.example")
        with patch.object(internet.socket, "getaddrinfo", return_value=_addresses("93.184.216.34")):
            self.assertEqual(internet.public_address("ok.example"), "93.184.216.34")

    def test_slow_download_hits_the_total_deadline(self):
        class Dripping:
            def read(self, _size):
                time.sleep(0.02)
                return b"x"
        with self.assertRaises(TimeoutError):
            internet._read_bounded(Dripping(), time.monotonic() + 0.1)


class BrowserPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.mind_root = patch.object(mind, "PROJECT_ROOT", Path(self.temp.name) / "mind")
        self.mind_root.start()
        self.runtime = create_runtime(Path(self.temp.name) / "state")

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def decide(self, name, arguments):
        tool = self.runtime.registry.get(name)
        return self.runtime.policy.authorize(tool, arguments, provenance="delegated", capability_allowed=True,
                                             autonomy="owner", tainted=False, exposed=False,
                                             owner_question=self.runtime.step_question(tool, arguments)).decision

    def test_agent_browser_on_a_local_address_asks(self):
        self.assertTrue(self.runtime.registry.get("browser.inspect").network_egress)
        with patch.object(internet.socket, "getaddrinfo", return_value=_addresses("192.168.1.1")):
            self.assertEqual(self.decide("browser.inspect", {"url": "http://router.local/", "browser": "edge"}),
                             Decision.CONFIRM)
        with patch.object(internet.socket, "getaddrinfo", return_value=_addresses("93.184.216.34")):
            self.assertEqual(self.decide("browser.inspect", {"url": "https://example.com/", "browser": "edge"}),
                             Decision.ALLOW)


class PathTests(unittest.TestCase):
    def test_unknown_appdata_refuses_every_change(self):
        with patch.object(paths, "_known_folder", return_value=None), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("USERPROFILE", None)
            reason = paths.protection_reason(Path("D:/ChutkuScratch/x.txt"))
        self.assertIn("AppData", reason)

    def test_appdata_comes_from_the_shell(self):
        root = paths.appdata_root()
        self.assertTrue(root and root.casefold().endswith("appdata"))
        self.assertIsNotNone(paths.protection_reason(Path(root) / "Roaming" / "x.txt"))


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.records = patch.object(documents, "_records_dir", return_value=self.root / "records")
        (self.root / "records").mkdir()
        self.records.start()

    def tearDown(self):
        self.records.stop()
        self.temp.cleanup()

    def test_organize_never_overwrites_a_file_that_appeared(self):
        folder = self.root / "Downloads"
        (folder / "Documents").mkdir(parents=True)
        (folder / "a.txt").write_text("mine", encoding="utf-8")
        (folder / "Documents" / "a.txt").write_text("appeared meanwhile", encoding="utf-8")
        context = ExecutionContext("t", None, self.root)
        with patch.object(documents, "_plan", return_value=[(folder / "a.txt", folder / "Documents" / "a.txt")]):
            result = documents._organize({"path": str(folder)}, context)
        self.assertEqual(result.output["moved"], 0)
        self.assertEqual((folder / "Documents" / "a.txt").read_text(encoding="utf-8"), "appeared meanwhile")
        self.assertEqual((folder / "a.txt").read_text(encoding="utf-8"), "mine")

    def test_undo_never_touches_a_protected_recorded_path(self):
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "chutku-should-never-touch.txt"
        record = {"folder": str(self.root), "moves": [{"from": str(windows), "to": str(self.root / "x.txt"),
                                                     "size": 1}]}
        (self.root / "x.txt").write_text("x", encoding="utf-8")
        (self.root / "records" / "organize-0000abcd.json").write_text(json.dumps(record), encoding="utf-8")
        result = documents._organize_undo({"id": "0000abcd"}, ExecutionContext("t", None, self.root))
        self.assertEqual(result.output["restored"], 0)
        self.assertTrue((self.root / "x.txt").exists())
        self.assertFalse(windows.exists())


class ActionLogFailClosedTests(unittest.TestCase):
    def test_an_unwritable_action_log_means_nothing_runs(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        ran = []
        with create_runtime(Path(temp.name) / "state") as runtime:
            runtime.registry.register(Tool("test.change", "test", Risk.REVERSIBLE,
                                           lambda a, c: ran.append(1) or ToolResult({}, Verification.PASS),
                                           argument_schema={"type": "object", "properties": {}}))
            runtime.action_log.path.parent.mkdir(parents=True, exist_ok=True)
            runtime.action_log.path.write_text('{"seq": 1}\n{broken', encoding="utf-8")
            result = runtime.run("test.change", {})
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("action log", result["error"])
        self.assertEqual(ran, [])


class TodayWeatherTests(unittest.TestCase):
    def test_weather_tile_needs_the_internet_grant(self):
        from chutku import today
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        (Path(temp.name) / "data").mkdir()
        with patch.object(internet, "_weather") as weather:
            today._refresh_weather(Path(temp.name))
        weather.assert_not_called()


if __name__ == "__main__":
    unittest.main()

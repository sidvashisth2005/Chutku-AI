from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import health


class HealthTests(unittest.TestCase):
    def test_real_readings_are_well_formed(self):
        data = health.readings()
        self.assertTrue(data["disk"])
        self.assertTrue(0 < data["memory"]["used_percent"] <= 100)
        if data["battery"] is not None:
            self.assertTrue(0 <= data["battery"]["percent"] <= 100)

    def test_problems(self):
        data = {"battery": {"percent": 15, "charging": False}, "memory": {"used_percent": 95, "free_gb": 0.4},
                "disk": [{"drive": "C:\\", "free_gb": 9.0, "free_percent": 3.5, "total_gb": 254}]}
        keys = [p[0] for p in health.problems(data)]
        self.assertEqual(keys, ["battery", "disk:C:\\", "memory"])
        calm = {"battery": {"percent": 15, "charging": True}, "memory": {"used_percent": 40, "free_gb": 8},
                "disk": [{"drive": "D:\\", "free_gb": 99, "free_percent": 52, "total_gb": 191}]}
        self.assertEqual(health.problems(calm), [])

    def test_rate_limits(self):
        disk = [("disk:C:\\", "t", "m", None)]
        alerts, state = health.due(disk, {}, now=1000)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(health.due(disk, state, now=1000 + 3600)[0], [])  # within 12 h
        self.assertEqual(len(health.due(disk, state, now=1000 + 13 * 3600)[0]), 1)

    def test_battery_alerts_once_per_threshold_and_rearms(self):
        at = lambda pct: [("battery", "t", f"{pct}", 10 if pct <= 10 else 20)]
        alerts, state = health.due(at(19), {})
        self.assertEqual(len(alerts), 1)
        alerts, state = health.due(at(15), state)
        self.assertEqual(alerts, [])
        alerts, state = health.due(at(9), state)
        self.assertEqual(len(alerts), 1)  # crossed 10%
        alerts, state = health.due([], state)  # plugged in
        self.assertEqual(len(health.due(at(18), state)[0]), 1)

    def test_check_sends_and_remembers(self):
        sent = []
        with tempfile.TemporaryDirectory() as temp, \
                patch("chutku.health.readings", return_value={"battery": None, "memory": {"used_percent": 30},
                      "disk": [{"drive": "C:\\", "free_gb": 9.0, "free_percent": 3.5, "total_gb": 254}]}):
            self.assertEqual(len(health.check(temp, send=lambda t, m: sent.append((t, m)))), 1)
            self.assertEqual(health.check(temp, send=lambda t, m: sent.append((t, m))), [])
            self.assertTrue((Path(temp) / "data" / "health-alerts.json").exists())
        self.assertEqual(len(sent), 1)
        self.assertIn("almost full", sent[0][0])


if __name__ == "__main__":
    unittest.main()

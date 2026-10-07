"""Two regressions the Night Shift found on 2026-10-07 (report-20261007.json), now fixed with instant rules.

- "Ita lag kar rahe." used to run system.health + system.performance; the model's new plan was empty.
- "Calculator download." used to open Calculator; the model's new plan opened Steam downloads (games.downloads).
"""
import unittest

from chutku.quick_intents import quick_proposal

APPS = [{"name": "Calculator", "app_id": "Microsoft.WindowsCalculator!App"},
        {"name": "Notepad", "app_id": "Microsoft.WindowsNotepad!App"},
        {"name": "Spotify", "app_id": "Spotify.App"}]

SLOW = ["Ita lag kar rahe.", "itna lag kar raha hai", "laptop lag kar raha hai", "pc hang ho raha hai",
        "laptop slow hai", "mera laptop bahut slow chal raha hai", "why is my pc so laggy", "why is my laptop so slow",
        "इतना लैग कर रहा है", "लैपटॉप स्लो है", "पीसी हैंग हो रहा है", "कंप्यूटर स्लो चल रहा है",
        "लैपटॉप बहुत लैग कर रहा है"]
NOT_SLOW = ["accha lag raha hai", "mujhe bhook lag rahi hai", "अच्छा लग रहा है", "slow", "lagging", "is it slow",
            "dil nahi lag raha"]


def tools(goal):
    proposal = quick_proposal(goal, apps=APPS)
    return [step["tool"] for step in proposal.get("next_steps", [])] if proposal else None


class SlowPcTests(unittest.TestCase):
    def test_complaints_check_what_is_using_the_pc(self):
        for goal in SLOW:
            self.assertEqual(tools(goal), ["system.performance"], goal)

    def test_feelings_and_bare_words_are_not_complaints(self):
        for goal in NOT_SLOW:
            self.assertNotEqual(tools(goal), ["system.performance"], goal)


class PerformanceAnswerTests(unittest.TestCase):
    OUT = {"cpu_percent": 8.9, "memory": {"used_percent": 77, "used_gib": 18.3, "total_gib": 23.7},
           "battery": {"percent": 95, "charging": True},
           "gpu": {"name": "RTX 3050", "utilization_percent": 0, "temperature_c": 53},
           "top_memory_processes": [{"name": "llama-server", "memory_mib": 3948}, {"name": "Code", "memory_mib": 809},
                                    {"name": "pythonw", "memory_mib": 782}, {"name": "Code", "memory_mib": 586}]}

    def test_says_load_and_what_uses_memory_instantly(self):
        from chutku.quick_intents import QUICK_ANSWERS
        text = QUICK_ANSWERS["system.performance"](self.OUT)
        for fact in ("CPU 9%", "RAM 77% used (18.3 of 23.7 GB)", "GPU 0% at 53°C", "my local brain (llama-server) 3.9 GB",
                     "VS Code 1.4 GB"):   # the two "Code" processes are added up
            self.assertIn(fact, text)
        self.assertNotIn("almost full", text)

    def test_warns_when_ram_or_cpu_is_full(self):
        from chutku.quick_intents import QUICK_ANSWERS
        busy = dict(self.OUT, cpu_percent=97, memory={"used_percent": 93, "used_gib": 22.0, "total_gib": 23.7})
        text = QUICK_ANSWERS["system.performance"](busy)
        self.assertIn("almost full", text)
        self.assertIn("very busy", text)


class DownloadInstalledAppTests(unittest.TestCase):
    def test_installed_app_is_opened_not_downloaded(self):
        for goal in ("Calculator download.", "calculator download karo", "download calculator", "install notepad"):
            proposal = quick_proposal(goal, apps=APPS)
            step = proposal["next_steps"][0]
            self.assertEqual(step["tool"], "apps.launch", goal)
            self.assertIn(step["arguments"]["name"], {"Calculator", "Notepad"})
            self.assertIn("already installed", proposal["reply"])

    def test_never_steam_downloads_for_an_app(self):
        self.assertNotIn("games.downloads", tools("Calculator download.") or [])

    def test_unknown_or_non_app_downloads_go_to_the_model(self):
        for goal in ("zzqxapp download karo", "download my resume", "download the pdf from this page"):
            self.assertIsNone(tools(goal), goal)


if __name__ == "__main__":
    unittest.main()

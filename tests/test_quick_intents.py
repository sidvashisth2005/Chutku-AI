import os
import tempfile
import unittest
from pathlib import Path

from chutku.agent_loop import AgentSession
from chutku.app import create_runtime
from chutku.quick_intents import QuickPlanner, quick_proposal

APPS = [{"name": "Spotify", "app_id": "Spotify.App"}, {"name": "Calculator", "app_id": "Microsoft.Calc!App"},
        {"name": "Visual Studio Code", "app_id": "Microsoft.VSCode"},
        {"name": "Visual Studio Installer", "app_id": "Microsoft.VS.Installer"}]


def step(text):
    proposal = quick_proposal(text, apps=APPS)
    return None if proposal is None else (proposal["next_steps"][0]["tool"], proposal["next_steps"][0]["arguments"])


class QuickIntentTests(unittest.TestCase):
    def test_disk_log_and_recent_phrases(self):
        for text in ("how much space is left", "check disk space", "storage kitna khali hai", "How much free space on my PC?"):
            self.assertEqual(step(text), ("system.disk_space", {}), text)
        self.assertEqual(step("what did you do today"), ("log.recent", {"today": True}))
        self.assertEqual(step("aaj kya kiya"), ("log.recent", {"today": True}))
        self.assertEqual(step("what have you done"), ("log.recent", {}))
        for text in ("what was I working on?", "show my recent files", "main kis file pe kaam kar raha tha"):
            self.assertEqual(step(text), ("files.recent", {"path": os.environ["USERPROFILE"]}), text)

    def test_daily_phrases(self):
        downloads = os.path.join(os.environ["USERPROFILE"], "Downloads")
        for text in ("organize my Downloads folder", "tidy up downloads", "downloads saaf karo"):
            self.assertEqual(step(text), ("files.organize", {"path": downloads}), text)
        self.assertEqual(step("lock my pc"), ("system.lock", {}))
        self.assertEqual(step("remember city = Delhi"), ("memory.remember", {"key": "city", "value": "Delhi"}))
        self.assertEqual(step("remember my city is Pune"), ("memory.remember", {"key": "city", "value": "Pune"}))
        self.assertEqual(step("kaunsa gaana chal raha hai"), ("media.status", {}))
        self.assertIsNone(step("remember x"))

    def test_instant_answers_never_trip_the_false_claim_guard(self):
        from chutku.agent_loop import _CLAIMS
        from chutku.quick_intents import QUICK_ANSWERS
        samples = {
            "system.get_time": {"local_time": "Friday, 02 October 2026, 11:00 AM"},
            "system.disk_space": {"drives": [{"drive": "C:\\", "free_gb": 9, "total_gb": 254, "free_percent": 3.6}],
                                  "advice": "Low space on C:\\. Ask me for the biggest files there, or empty the Recycle Bin."},
            "files.recent": {"files": [{"name": "a.txt", "modified": "2026-10-01 10:00"}], "days": 7, "searched": []},
            "log.recent": {"actions": [{"id": 1, "tool": "filesystem.recycle", "state": "COMPLETED"}], "count": 1,
                           "chain_ok": True},
            "routine.list": {"routines": {"work": ["open spotify"]}},
            "media.status": {"title": "Song", "artist": "Band"},
            "audio.outputs": {"devices": [{"name": "Speakers", "default": True}, {"name": "Headphones", "default": False}]},
            "image.describe": {"description": "A cat sitting on a sofa next to a window."},
            "screen.understand": {"summary": "VS Code with a Python file open.", "answer": ""},
            "note.list": {"items": [{"id": 1, "text": "buy milk", "done": False}]},
            "message.send": {"app": "WhatsApp", "to": "UB", "text": "hi", "seen_in_chat": True,
                             "tip": "Save their number once ('remember contact_ub = +91...')."},
            "system.gpu_status": {"gpus": [{"name": "RTX 3050", "driver_version": "596", "vram_mib": "4096"}]},
            "system.environment": {"windows_version": "10.0.26200", "machine": "AMD64",
                                   "drives": [{"drive": "C:", "free_gib": 8.4}]},
            "system.volume_status": {"level": 28, "muted": False},
            "settings.theme_status": {"apps": "dark", "system": "dark"},
            "system.health": {"battery": {"percent": 13, "charging": False}, "memory": {"used_percent": 54, "free_gb": 10.8},
                              "disk": [{"drive": "C:\\", "free_gb": 8.4, "low": True}]},
            "net.check": {"verdict": "Internet works (40 ms to Google).", "local_ip": "192.168.1.5", "public_ip": "1.2.3.4"},
            "net.ping": {"host": "google.com", "sent": 4, "received": 4, "average_ms": 60, "unknown_host": False},
            "files.find": {"query": "resume", "count": 1, "matches": [
                {"name": "Resume.pdf", "folder": "Downloads", "modified": "2026-10-01 10:00"}]},
            "storage.cleanup_report": {"drive": "C:\\", "suggestions": [
                "Empty the Recycle Bin on C: (2 GB, 10 items)", "Recycle 2 old installer(s) in Downloads (1 GB)",
                "Your own files are small here: most of the drive is Windows, your programs and app caches"]},
            "screen.displays": {"displays": [{"width": 1536, "height": 864, "primary": True}], "count": 1},
            "display.brightness_status": {"level": 65},
            "games.list": {"games": [{"store": "Epic", "name": "Fall Guys", "state": "installed"},
                                     {"store": "Steam", "name": "Portal 2", "state": "needs update"}], "count": 2},
            "apps.installed": {"query": "VLC", "apps": [{"name": "VLC media player"}], "count": 1, "truncated": False},
            "mind.who": {"name": "gf", "known": True, "person": {"name": "UB", "aliases": ["gf"], "relation": "",
                                                                  "whatsapp": "", "phone": ""}},
            "mind.show": {"part": "all", "people": [{"name": "UB", "aliases": ["gf"]}], "facts": {"home": "Pune"},
                          "lists": {"assignments": [{"id": 1, "text": "DBMS report", "done": True}]}},
        }
        samples["network.status"] = {"adapters": [{"Name": "Wi-Fi", "Status": "Up", "LinkSpeed": "907 Mbps"},
                                                   {"Name": "Ethernet", "Status": "Disconnected"}], "count": 2}
        samples["filesystem.list"] = {"path": "D:\\ChutkuBench", "entries": ["todo.txt", "logs"]}
        samples["message.read_chat"] = {"to": "Pita Shri", "count": 2, "messages": [
            {"from": "you", "text": "hi"}, {"from": "them", "text": "haan beta"}]}
        samples["message.open_chat"] = {"app": "WhatsApp", "to": "Pita Shri", "chat_opened": True, "typed": False}
        samples["windows.list"] = {"windows": [{"title": "notes.txt - Notepad", "executable": "notepad.exe"}]}
        samples_empty = {"apps.installed": {"query": "Steam", "apps": [], "count": 0, "truncated": False}}
        samples_empty["mind.who"] = {"name": "mammi", "known": False}
        samples_empty["mind.show"] = {"part": "all", "people": [], "facts": {}, "lists": {}}
        for tool, output in samples_empty.items():
            for pattern, _prefixes in _CLAIMS:
                self.assertIsNone(pattern.search(QUICK_ANSWERS[tool](output)), tool)
        self.assertEqual(set(samples), set(QUICK_ANSWERS))
        for tool, output in samples.items():
            text = QUICK_ANSWERS[tool](output)
            for pattern, _prefixes in _CLAIMS:
                self.assertIsNone(pattern.search(text), (tool, text))

    def test_simple_questions_answer_without_the_model(self):
        from chutku.agent_loop import RuntimeRouter, default_context

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model planner must not be needed")

        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            router = RuntimeRouter(runtime)
            try:
                for goal, expected in (("what time is it", "It's "), ("check disk space", " GB free of ")):
                    session = AgentSession(goal, mode="auto_safe", context=default_context(router))
                    session.quick = QuickPlanner()
                    snapshot = session.advance(router, NoModel())
                    self.assertEqual(snapshot["status"], "done", snapshot)
                    self.assertIn(expected, snapshot["reply"])
            finally:
                router.close()

    def test_small_talk_and_two_installed_checks_answer_without_the_model(self):
        from chutku.agent_loop import RuntimeRouter, default_context

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model planner must not be needed")

            def answer(self, *args, **kwargs):
                raise AssertionError("an instant answer must not be reworded by the model")

        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            router = RuntimeRouter(runtime)
            try:
                for goal, expected in (("Hi Chutku, how are you?", "badhiya"), ("thank you", "Anytime"),
                                       ("Is Zzqx or Qqzx installed on this PC?", "Qqzx isn't installed"),
                                       ("what time is it", "It's "), ("check disk space", " GB free of ")):
                    session = AgentSession(goal, mode="auto_safe", context=default_context(router))
                    session.quick = QuickPlanner()
                    snapshot = session.advance(router, NoModel())
                    self.assertEqual(snapshot["status"], "done", snapshot)
                    self.assertIn(expected, snapshot["reply"])
            finally:
                router.close()

    def test_read_file_requests_read_the_text_first(self):
        self.assertEqual(step(r"Read D:\ChutkuBench\todo.txt and tell me the first task."),
                         ("file.extract_text", {"path": r"D:\ChutkuBench\todo.txt"}))
        self.assertEqual(step(r"padh ke batao D:\Notes\plan.docx"), None)            # not this word order
        self.assertEqual(step(r"read D:\Notes\plan.docx"), ("file.extract_text", {"path": r"D:\Notes\plan.docx"}))
        self.assertIsNone(step("read my mind"))

    def test_folder_listing_and_hinglish_time_are_instant(self):
        for text in (r"What files are in D:\ChutkuBench?", r"list the files in D:\ChutkuBench",
                     r"D:\ChutkuBench mein kya hai", r"what's in D:\ChutkuBench folder"):
            self.assertEqual(step(text), ("filesystem.list", {"path": "D:\\ChutkuBench"}), text)
        self.assertEqual(step("what files are in D:"), ("filesystem.list", {"path": "D:\\"}))
        for text in ("time kya hua hai abhi", "abhi kya time hai", "kya time ho gaya hai"):
            self.assertEqual(step(text), ("system.get_time", {}), text)
        self.assertIsNone(step("what files are in my downloads that are big"))

    def test_which_adapter_question_also_lists_adapters(self):
        from chutku.quick_intents import QUICK_ANSWERS
        tools = [s["tool"] for s in quick_proposal("Am I connected to the network? Which adapter is up?", apps=[])["next_steps"]]
        self.assertEqual(tools, ["net.check", "network.status"])
        self.assertEqual([s["tool"] for s in quick_proposal("am i online", apps=[])["next_steps"]], ["net.check"])
        text = QUICK_ANSWERS["network.status"]({"adapters": [
            {"Name": "Wi-Fi", "Status": "Up", "LinkSpeed": "907 Mbps", "MacAddress": "68-7A"},
            {"Name": "Ethernet", "Status": "Disconnected", "LinkSpeed": "0 bps"}]})
        self.assertEqual(text, "Wi-Fi is up, 907 Mbps; Ethernet is disconnected.")
        self.assertNotIn("68-7A", text)                                       # no MAC address in answers

    def test_info_questions_match_whole_sentences_only(self):
        # verify_agent_chat 2026-10-04: "Which windows are open..." was answered with the Windows version.
        self.assertNotEqual((step("Which windows are open right now? Just list the app names.") or ("",))[0],
                            "system.environment")
        self.assertNotEqual((step("which gpu games run best on my laptop") or ("",))[0], "system.gpu_status")
        self.assertEqual(step("Which Windows version is this PC running?"), ("system.environment", {}))
        self.assertEqual(step("what windows version do i have"), ("system.environment", {}))
        self.assertEqual(step("Which graphics card do I have and how much VRAM?"), ("system.gpu_status", {}))

    def test_new_question_phrasings_and_their_boundaries(self):
        self.assertEqual(step("D drive mein kitni jagah khali hai?"), ("system.disk_space", {}))
        self.assertEqual(step("Is VLC or Spotify installed on this PC?"), ("apps.installed", {"query": "VLC"}))
        self.assertEqual(len(quick_proposal("Is VLC or Spotify installed on this PC?", apps=[])["next_steps"]), 2)
        for text in ("is it installed", "hi, open spotify and delete my files", "how many files are in downloads",
                     "what is the capital of France"):
            proposal = quick_proposal(text, apps=[])
            self.assertTrue(proposal is None or proposal["next_steps"], text)  # never a chatty reply that drops a task
        self.assertIsNone(quick_proposal("hello and open spotify", apps=[{"name": "Spotify", "app_id": "S"}]))

    def test_install_claim_rule_flags_actions_not_states(self):
        from chutku.agent_loop import _CLAIMS
        def flagged(text):
            return any(pattern.search(text) for pattern, _prefixes in _CLAIMS)
        for text in ("I installed VLC.", "Spotify has been installed.", "Successfully installed Steam."):
            self.assertTrue(flagged(text), text)
        for text in ("Spotify is installed on this PC.", "Yes, VLC: VLC media player.", "Steam isn't installed."):
            self.assertFalse(flagged(text), text)

    def test_open_apps_english_and_hinglish(self):
        for text in ("open spotify", "Please launch the Calculator app.", "start Visual Studio Code",
                     "spotify kholo", "calculator khol do", "Oye Chutku, open Spotify please"):
            self.assertEqual(step(text)[0], "apps.launch", text)
        self.assertEqual(step("spotify kholo")[1], {"name": "Spotify"})

    def test_unclear_app_names_go_to_windows_search_and_compound_requests_fall_through(self):
        # Two apps fit / not an exact name: apps.launch asks Windows search (2026-10-04 owner request).
        self.assertEqual(step("open visual studio"), ("apps.launch", {"name": "visual studio"}))
        self.assertEqual(step("open photoshop"), ("apps.launch", {"name": "photoshop"}))
        for text in ("open notes folder", r"open D:\Notes\a.txt", "open the newest pdf file", "open it",
                     "what is the time in London", "delete everything"):
            self.assertIsNone(step(text), text)

    def test_web_search_and_sites(self):
        self.assertEqual(step("Search YouTube for lofi hip hop music."),
                         ("web.search", {"query": "lofi hip hop music", "site": "youtube"}))
        self.assertEqual(step("search python tutorials on google"),
                         ("web.search", {"query": "python tutorials", "site": "google"}))
        self.assertEqual(step("youtube pe arijit singh songs chalao"),
                         ("youtube.play", {"query": "arijit singh songs"}))
        self.assertEqual(step("youtube pe arijit singh songs search karo"),
                         ("web.search", {"query": "arijit singh songs", "site": "youtube"}))
        self.assertEqual(step("google weather in delhi"), ("web.search", {"query": "weather in delhi", "site": "google"}))
        self.assertEqual(step("open youtube.com"), ("web.open", {"url": "https://youtube.com"}))

    def test_time_phrases_english_and_hinglish(self):
        for text in ("what time is it", "What time it is?", "Abhi kite ne baje hain?", "kitne baje hai", "time batao"):
            self.assertEqual(step(text), ("system.get_time", {}), text)

    def test_parity_phrases(self):
        cases = {
            "What's the weather in Delhi right now?": ("web.weather", {"city": "Delhi"}),
            "Pune ka mausam kaisa hai": ("web.weather", {"city": "Pune"}),
            "Give me the latest news about cricket": ("web.news", {"topic": "cricket"}),
            "khabar batao": ("web.news", {}),
            "play arijit singh songs on youtube": ("youtube.play", {"query": "arijit singh songs"}),
            "Turn the volume up a little": ("audio.volume", {"action": "up"}),
            "awaaz kam karo": ("audio.volume", {"action": "down"}),
            "set volume to 30": ("audio.volume", {"action": "set", "level": 30}),
            "mute": ("audio.volume", {"action": "mute"}),
            "brightness kam karo": ("display.brightness", {"action": "down"}),
            "set brightness to 40": ("display.brightness", {"action": "set", "level": 40}),
            "remind me in 10 minutes to drink water": ("reminder.set", {"message": "drink water", "in_minutes": 10}),
            "set a timer for 5 minutes": ("reminder.set", {"message": "Your timer is done.", "in_minutes": 5}),
        }
        for text, expected in cases.items():
            self.assertEqual(step(text), expected, text)
        self.assertIsNone(step("set volume to 300"))
        self.assertIsNone(step("remind me at 5 to call mom"))  # am or pm? the model asks

    def test_open_and_play_chain(self):
        chain = quick_proposal("open spotify and play music", apps=APPS)
        self.assertEqual([s["tool"] for s in chain["next_steps"]], ["apps.launch", "media.control"])

    def test_close_and_compound_requests(self):
        self.assertEqual(step("close spotify"), ("apps.quit", {"name": "spotify"}))
        self.assertEqual(step("spotify band karo"), ("apps.quit", {"name": "spotify"}))
        self.assertEqual(step("gaana band karo"), ("media.control", {"action": "pause"}))
        self.assertEqual(step("stop the music"), ("media.control", {"action": "pause"}))
        self.assertEqual(step("close the tab"), ("keyboard.edit", {"action": "close_tab"}))
        for unclear in ("close it", "close everything", "shut down the computer"):
            self.assertIsNone(step(unclear), unclear)
        chain = quick_proposal("Open Calculator and then close it", apps=APPS)
        self.assertEqual([(s["tool"], s["arguments"]) for s in chain["next_steps"]],
                         [("apps.launch", {"name": "Calculator"}), ("apps.quit", {"name": "Calculator"})])
        self.assertIsNone(quick_proposal("open notepad and write a poem about rain", apps=APPS))  # model plans that
        self.assertEqual(step("search youtube for tom and jerry"),
                         ("web.search", {"query": "tom and jerry", "site": "youtube"}))  # whole match wins

    def test_build_requests_go_to_the_project_builder(self):
        for text, slug in (("build me a calculator app", "calculator-app"), ("ek calculator app banao", "calculator-app"),
                           ("Oye Chutku, make a snake game in the browser", "snake-game-browser"),
                           ("mere liye ek portfolio website bana do", "portfolio-website")):
            tool, arguments = step(text)
            self.assertEqual(tool, "code.build_project", text)
            self.assertTrue(arguments["path"].endswith("\\" + slug), arguments)
        for text in ("make a folder called apps", "create a new document", "write a note", "build the project",
                     r"Write 'hacked' into C:\Program Files\chutku.txt", r"create D:\apps\game.txt"):
            self.assertNotEqual((step(text) or ("",))[0], "code.build_project", text)

    def test_media(self):
        self.assertEqual(step("pause the music"), ("media.control", {"action": "pause"}))
        self.assertEqual(step("next song"), ("media.control", {"action": "next"}))
        self.assertEqual(step("gaana roko"), ("media.control", {"action": "pause"}))

    def test_quick_planner_runs_through_policy_and_finishes_in_one_round(self):
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            session = AgentSession("pause the music", mode="auto_safe")
            session.quick = QuickPlanner()

            class NoLLM:
                name = "local"

                def propose(self, *a, **k):
                    raise AssertionError("language model should not be needed")
            snap = session.advance(runtime, NoLLM())
            # audio.modify is not granted in this temp profile: policy still decides.
            self.assertEqual(snap["status"], "stopped")
            self.assertEqual(snap["steps"][0]["tool"], "media.control")
            self.assertEqual(snap["steps"][0]["state"], "DENIED")


if __name__ == "__main__":
    unittest.main()

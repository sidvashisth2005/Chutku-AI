"""The owner's real words (live voice session 2026-10-04, plus Hindi-script and Hinglish variants).

Each case says what Chutku must do. These goals came from the voice model's rewrites in data/experience.jsonl and
data/actions.log.jsonl; before the fix they became Google searches, an "app" called "youtube.com in brave browser",
and failed launches of "brave browser".
"""
import unittest
from unittest.mock import patch

from chutku.quick_intents import quick_proposal
from chutku.translit import roman

APPS = [{"name": "Brave", "app_id": "Brave"}, {"name": "WhatsApp", "app_id": "WhatsApp"},
        {"name": "Spotify", "app_id": "Spotify.App"}, {"name": "Calculator", "app_id": "Calc"},
        {"name": "Microsoft Edge", "app_id": "MSEdge"}, {"name": "Google Chrome", "app_id": "Chrome"}]


def steps(text):
    proposal = quick_proposal(text, apps=APPS)
    return None if proposal is None else [(s["tool"], s["arguments"]) for s in proposal["next_steps"]]


REAL = [
    # WhatsApp: open the chat (owner: then ask what to send)
    ('search for "पिता श्री" in WhatsApp contact list', [("message.open_chat", {"app": "whatsapp", "to": "pita shri"})]),
    ('search for "पिता श्री" in WhatsApp', [("message.open_chat", {"app": "whatsapp", "to": "pita shri"})]),
    ('search for "Pita Shri" in WhatsApp', [("message.open_chat", {"app": "whatsapp", "to": "Pita Shri"})]),
    ("open Pita Shri's chat on WhatsApp", [("message.open_chat", {"app": "whatsapp", "to": "Pita Shri"})]),
    ("WhatsApp pe Pita Shri ki chat kholo", [("message.open_chat", {"app": "whatsapp", "to": "Pita Shri"})]),
    ("व्हाट्सएप पे पिता श्री की चैट खोलो", None),   # all-Hindi: falls to the model (never a Google search)
    # Brave
    ("open youtube.com in brave browser", [("web.open", {"url": "https://youtube.com", "browser": "brave"})]),
    ('type "youtube.com" in Brave\'s address bar and press Enter',
     [("web.open", {"url": "https://youtube.com", "browser": "brave"})]),
    ('search for "Latent Season 2 latest episode" on YouTube in Brave browser',
     [("web.search", {"query": "Latent Season 2 latest episode", "site": "youtube", "browser": "brave"})]),
    ("play Latent season 2 latest episode on youtube in brave",
     [("youtube.play", {"query": "Latent season 2 latest episode", "browser": "brave"})]),
    ("Brave mein youtube kholo", [("web.open", {"url": "https://www.youtube.com", "browser": "brave"})]),
    ("open brave browser", [("apps.launch", {"name": "Brave"})]),
    ("brave browser kholo", [("apps.launch", {"name": "Brave"})]),
    ("open Brave", [("apps.launch", {"name": "Brave"})]),
    ("search python tutorials in chrome", [("web.search", {"query": "python tutorials", "site": "google", "browser": "chrome"})]),
]


class RealSessionTests(unittest.TestCase):
    def test_real_goals_do_the_right_thing(self):
        for text, expected in REAL:
            self.assertEqual(steps(text), expected, text)

    def test_never_a_google_search_for_something_inside_an_app(self):
        for text in ('search for "पिता श्री" in WhatsApp contact list', "search for UB in whatsapp",
                     "search lofi in spotify", "search Pita Shri in telegram"):
            result = steps(text) or []
            self.assertFalse(any(tool == "web.search" and args.get("site", "google") == "google" for tool, args in result),
                             text)

    def test_app_names_never_contain_a_browser_or_place(self):
        for text in ("open youtube.com in brave browser", "open gmail in chrome", "open notes in onenote"):
            for tool, args in steps(text) or []:
                if tool == "apps.launch":
                    self.assertNotRegex(args["name"], r"\s(?:in|on)\s", text)

    def test_follow_up_message_goes_to_the_chat_just_opened(self):
        from chutku.tools import apps_extra
        with patch.object(apps_extra, "recent_chat", return_value=("whatsapp", "Pita Shri")):
            self.assertEqual(steps("hi bhej do"), [("message.send", {"app": "whatsapp", "to": "Pita Shri", "text": "hi"})])
            self.assertEqual(steps('send "good night"'),
                             [("message.send", {"app": "whatsapp", "to": "Pita Shri", "text": "good night"})])
            self.assertEqual(steps("send hi to UB on whatsapp")[0][1]["to"], "UB")   # a named person wins
            for text in (r"Write 'x' into D:\\ChutkuBench\\x.txt", "open notepad and write a poem about rain",
                         "write a poem about rain", r"send D:\\x\\a.txt to UB", "what time is it"):
                for tool, args in steps(text) or []:
                    self.assertFalse(tool == "message.send" and args.get("to") == "Pita Shri", text)
        with patch.object(apps_extra, "recent_chat", return_value=None):
            self.assertNotEqual((steps("hi bhej do") or [("", {})])[0][0], "message.send")   # no open chat: no guess

    def test_hindi_script_names_reach_the_saved_person(self):
        import tempfile
        from pathlib import Path
        from chutku import mind
        with tempfile.TemporaryDirectory() as temp, patch.object(mind, "PROJECT_ROOT", Path(temp)):
            mind.default().remember_person("UB", aliases=["mammi"])
            self.assertEqual(steps("मम्मी ko good night bhejo"),
                             [("message.send", {"app": "whatsapp", "to": "mammi", "text": "good night"})])
            self.assertEqual(mind.default().find_person("मम्मी")["name"], "UB")

    def test_hindi_script_is_read_as_hinglish(self):
        self.assertEqual(roman("पिता श्री"), "pita shri")
        self.assertEqual(roman("मम्मी"), "mammi")
        self.assertEqual(roman("हाँ भेज दो"), "haan bhej do")
        self.assertEqual(roman("नहीं"), "nahin")
        self.assertEqual(roman("Brave"), "Brave")


class LenientApprovalTests(unittest.TestCase):
    def test_spoken_answers(self):
        from chutku.voice.approval import decide
        yes = ["हाँ", "हां", "हम्म", "हाँ भेज दो", "हाँ जी", "जी", "ठीक है", "कर दो", "haan", "hnn", "hmm", "yep", "ok",
               "bilkul", "theek hai bhej do", "sahi hai", "chalo", "haan bhai"]
        no = ["नहीं", "मत करो", "रुको", "हाँ नहीं", "abhi nahi", "no", "cancel", "yes but wait", "ruk jao"]
        unclear = ["hmm let me think about the weather tomorrow", "the weather in mumbai is very hot and sunny today",
                   "hello", ""]
        for heard in yes:
            self.assertIs(decide(heard), True, heard)
        for heard in no:
            self.assertIs(decide(heard), False, heard)
        for heard in unclear:
            self.assertIsNone(decide(heard), heard)


if __name__ == "__main__":
    unittest.main()

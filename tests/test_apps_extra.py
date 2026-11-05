import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.app import create_runtime
from chutku.tools import apps_extra
from chutku.tools.registry import Risk


class MessagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("desktop.input")

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def test_contacts_are_never_guessed(self):
        memory = self.runtime.memory
        self.assertEqual(apps_extra.resolve_contact("+91 98765 43210", memory)[0], "+919876543210")
        with self.assertRaisesRegex(ValueError, "remember contact_ravi"):
            apps_extra.resolve_contact("Ravi", memory)
        memory.save("contact_ravi", "+91 98765 00000")
        self.assertEqual(apps_extra.resolve_contact("ravi", memory)[0], "+919876500000")
        memory.save("contact_bad", "not a number")
        with self.assertRaises(ValueError):
            apps_extra.resolve_contact("bad", memory)

    def test_send_always_needs_on_screen_confirmation_before_anything(self):
        self.assertEqual(self.runtime.registry.get("message.send").base_risk, Risk.EXTERNAL_SIDE_EFFECT)
        with patch("os.startfile") as start:
            waiting = self.runtime.run("message.send", {"app": "whatsapp", "to": "+919876543210", "text": "hi"})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        start.assert_not_called()
        self.assertEqual(waiting["approval"]["arguments"]["text"], "hi")  # the exact text is shown for approval

    def test_unverified_send_is_not_reported_as_success(self):
        waiting = self.runtime.run("message.send", {"app": "whatsapp", "to": "+919876543210", "text": "hello there"})
        with patch("os.startfile"), patch.object(apps_extra, "_message_window",
                                                  return_value=(type("D", (), {"foreground": lambda s: 5})(),
                                                                {"window_id": 5, "title": "WhatsApp"})), \
                patch("chutku.tools.windows_apps.WindowsDesktop"), \
                patch("chutku.tools.desktop_controls.press_combo"), patch("time.sleep"), \
                patch("chutku.tools.documents.ocr", return_value=("some other chat text", "en")):
            done = self.runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(done["state"]), "FAILED")

    def test_validation(self):
        validate = self.runtime.registry.get("message.send").validate_arguments
        for bad in ({"app": "sms", "to": "x", "text": "y"}, {"app": "whatsapp", "to": "x", "text": "a\nb"},
                    {"app": "whatsapp", "to": "", "text": "y"}):
            with self.assertRaises(ValueError):
                validate(bad)


class QuitTests(unittest.TestCase):
    def test_matching_never_includes_chutku_page_and_confirms_first(self):
        windows = {1: {"window_id": 1, "process_id": 1, "title": "Spotify Premium", "executable": r"C:\s\Spotify.exe"},
                   2: {"window_id": 2, "process_id": 2, "title": "Chutku - Microsoft Edge", "executable": r"C:\e\msedge.exe"},
                   3: {"window_id": 3, "process_id": 3, "title": "News - Microsoft Edge", "executable": r"C:\e\msedge.exe"}}

        class Fake:
            def windows(self):
                return list(windows)

            def describe(self, hwnd):
                return windows[hwnd]
        with patch("chutku.tools.everyday.Desktop", return_value=Fake()):
            self.assertEqual([w["window_id"] for w in apps_extra.matching_windows("spotify")[1]], [1])
            _desktop, found, skipped = apps_extra.matching_windows("msedge")
        self.assertEqual([w["window_id"] for w in found], [3])
        self.assertTrue(skipped)
        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("desktop.input")
            waiting = runtime.run("apps.quit", {"name": "Spotify"})
            self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")


class GamesTests(unittest.TestCase):
    def test_steam_library_parsing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "steamapps").mkdir()
            (root / "steamapps" / "appmanifest_1.acf").write_text(
                '"AppState"\n{\n"appid" "570"\n"name" "Dota 2"\n"StateFlags" "6"\n"SizeOnDisk" "1073741824"\n}')
            (root / "steamapps" / "appmanifest_2.acf").write_text('"appid" "228980"\n"name" "Steamworks Common Redistributables"')
            with patch.object(apps_extra, "_steam_root", return_value=root):
                games = apps_extra.steam_games()
        self.assertEqual(games, [{"store": "Steam", "name": "Dota 2", "id": "570", "state": "needs update",
                                  "size_gib": 1.0}])

    def test_ambiguous_game_name_asks(self):
        games = [{"store": "Steam", "name": "Game One", "id": "1"}, {"store": "Steam", "name": "Game Two", "id": "2"}]
        with patch.object(apps_extra, "steam_games", return_value=games), patch.object(apps_extra, "epic_games", return_value=[]):
            with self.assertRaisesRegex(ValueError, "Which game"):
                apps_extra._find_game("game")
            self.assertEqual(apps_extra._find_game("game two")["id"], "2")


if __name__ == "__main__":
    unittest.main()


class NamedChatTests(unittest.TestCase):
    def test_header_must_be_exactly_the_requested_name(self):
        from chutku.tools.apps_extra import chat_header_matches
        self.assertTrue(chat_header_matches("Pita Shri\nlast seen today", "pita shri"))
        self.assertTrue(chat_header_matches("Pita Shri.", "Pita Shri"))
        for header in ("Pita Shri Ji Office", "Mata Shri", "", "Shri"):
            self.assertFalse(chat_header_matches(header, "Pita Shri"), header)

    # Real layout of the owner's WhatsApp 2.2638 window (maximised, 1938x1038 at -9,-9), from local OCR.
    RECT = (-9, -9, 1929, 1029)
    BASE = [{"text": "WhatsApp", "rect": (56, 16, 125, 31)}, {"text": "Chats", "rect": (108, 77, 177, 98)},
            {"text": "All", "rect": (122, 205, 143, 219)}, {"text": "Unread 18", "rect": (186, 205, 265, 219)},
            {"text": "Favourites", "rect": (308, 205, 390, 219)}, {"text": "Groups 6", "rect": (433, 206, 504, 223)},
            {"text": "Tech Clubs (All)", "rect": (189, 326, 328, 347)}, {"text": "11:58 am", "rect": (497, 331, 558, 342)},
            {"text": "Yesterday", "rect": (493, 425, 558, 440)}]

    def lines(self, *extra):
        return self.BASE + [{"text": text, "rect": rect} for text, rect in extra]

    def test_layout_is_read_from_the_screen(self):
        from chutku.tools.apps_extra import _header_matches, _search_box, _split_panes
        listed, pane_x = _split_panes(self.BASE, self.RECT)
        self.assertEqual(pane_x, 563)  # right edge of the chat list's timestamps
        self.assertEqual(_search_box(self.BASE, self.RECT, pane_x), (277, 151))  # between "Chats" and the chips
        self.assertEqual(_header_matches(self.lines(("AK", (620, 30, 660, 50))), self.RECT, "AK"), 563)
        self.assertIsNone(_header_matches(self.lines(("AK Office", (620, 30, 700, 50))), self.RECT, "AK"))

    def run_flow(self, screens, *, dry_run=True, row_light=None, text="hi"):
        from unittest.mock import patch
        from types import SimpleNamespace
        import numpy as np
        from chutku import vision
        from chutku.tools import apps_extra, desktop_controls
        window = {"window_id": 5, "process_id": 1, "title": "WhatsApp", "executable": "WhatsApp.Root.exe"}
        fake_desktop = SimpleNamespace(foreground=lambda: 5)
        shot = vision.Shot(np.zeros((10, 10, 3), np.uint8), 0, 0, 10, 10)
        typed, clicks, keys = [], [], []
        state = {"i": 0}

        def read_lines(_shot, _rect):
            screen = screens[min(state["i"], len(screens) - 1)]
            return screen

        def fake_rows(_shot, lines, _rect):
            # A list row = a name line below the filter chips; "green" marks WhatsApp's whole-name highlight.
            return [{"text": line["text"], "rect": line["rect"], "highlight": 1.0 if line.get("green") else 0.1}
                    for line in lines if line["rect"][1] > 230 and line["rect"][0] >= 180
                    and not apps_extra._TIMESTAMP.match(line["text"])]

        def on_type(text):
            typed.append(text)
            state["i"] += 1

        def on_click(x, y):
            clicks.append((x, y))
            if typed:
                state["i"] += 1
        def brightness(_shot, box):  # a list row turns lighter once that chat is clicked open
            return 50 if ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2) in clicks else 30
        with patch.object(apps_extra, "_message_window", return_value=(fake_desktop, window)), \
                patch("chutku.tools.windows_apps.WindowsDesktop"), \
                patch.object(apps_extra, "_window_rect", return_value=self.RECT), \
                patch.object(apps_extra.time, "sleep"), \
                patch.object(desktop_controls, "press_combo", side_effect=keys.append), \
                patch.object(desktop_controls, "type_unicode", side_effect=on_type), \
                patch.object(vision, "capture", return_value=shot), \
                patch.object(vision, "read_lines", side_effect=read_lines), \
                patch.object(vision, "click_at", side_effect=on_click), \
                patch.object(apps_extra, "_result_rows", side_effect=fake_rows), \
                patch.object(apps_extra, "_row_brightness", side_effect=row_light or brightness), \
                patch.object(vision, "read_strips", return_value=[""]):
            result = apps_extra._send_to_named_chat("AK", text, dry_run=dry_run)
        return result, typed, clicks, keys

    def test_chat_already_open_in_front_gets_the_message_without_searching_again(self):
        """Owner 2026-10-05: a second message to the open chat searched and reopened it every time."""
        open_ub = self.BASE + [{"text": "AK", "rect": (620, 30, 660, 50)}]
        sent = open_ub + [{"text": "hi", "rect": (900, 600, 930, 615)}]
        result, typed, clicks, _keys = self.run_flow([open_ub, sent], dry_run=False)
        self.assertEqual(result.verification.name, "PASS", result.output)
        self.assertTrue(result.output["chat_was_open"])
        self.assertEqual(typed, ["hi"])          # only the message: no name typed into search
        self.assertEqual(clicks, [])             # nothing clicked: no search box, no chat row

    def test_a_different_chat_in_front_still_goes_through_search(self):
        other_open = self.BASE + [{"text": "Mata Shri", "rect": (620, 30, 700, 50)}]
        searched = self.lines(("AK", (120, 145, 140, 160)), ("AK", (190, 330, 215, 347)))
        opened = searched + [{"text": "AK", "rect": (620, 30, 660, 50)}]
        result, typed, clicks, _keys = self.run_flow([other_open, searched, opened])
        self.assertEqual(result.verification.name, "PASS", result.output)
        self.assertFalse(result.output["chat_was_open"])
        self.assertEqual(typed, ["AK"])          # searched for the right chat first
        self.assertEqual(clicks[0], (277, 151))

    def test_emoji_only_message_is_confirmed_by_a_new_bubble_in_the_chat_area(self):
        import numpy as np
        from chutku import vision
        from chutku.tools.apps_extra import _area_changed
        before = vision.Shot(np.zeros((100, 200, 3), np.uint8), 0, 0, 200, 100)
        bubble = before.pixels.copy()
        bubble[40:70, 120:190] = 200                       # a new bubble inside the chat area
        typing = before.pixels.copy()
        typing[92:99, 10:190] = 200                        # only the compose box changed (outside the area)
        area = (100, 15, 200, 90)
        self.assertTrue(_area_changed(before, vision.Shot(bubble, 0, 0, 200, 100), area))
        self.assertFalse(_area_changed(before, vision.Shot(typing, 0, 0, 200, 100), area))

    def test_exact_chat_is_opened_and_confirmed_without_typing_a_message(self):
        searched = self.lines(("AK", (120, 145, 140, 160)), ("AK", (190, 330, 215, 347)))
        opened = searched + [{"text": "AK", "rect": (620, 30, 660, 50)}]
        result, typed, clicks, _keys = self.run_flow([self.BASE, searched, opened])
        self.assertEqual(result.verification.name, "PASS", result.output)
        self.assertTrue(result.output["chat_confirmed"])
        self.assertEqual(typed, ["AK"])                       # only the search text, never the message
        self.assertEqual(clicks, [(277, 151), (202, 338)])     # search box, then the exact row

    def test_short_name_found_by_whatsapps_green_highlight_not_ocr(self):
        """Owner's screenshot 2026-10-03: "Ak" is the 4th result, drawn in green; OCR could not read it."""
        results = self.lines(("Pushkar Dubey ICMME Team JU...", (190, 327, 488, 346)),
                             ("Train With Shubham", (189, 422, 367, 437)), ("Tech Clubs (All)", (189, 516, 328, 537)),
                             ("", (189, 612, 215, 627)), ("Pankaj Dubey Sir", (190, 707, 491, 726)))
        results[-2]["green"] = True                                    # the unreadable, fully highlighted "Ak"
        searched = [{"text": "x", "rect": (538, 148, 553, 163)}] + results
        opened = searched + [{"text": "", "rect": (620, 30, 660, 50)}]  # header not OCR-readable either
        result, typed, clicks, _keys = self.run_flow([self.BASE, searched, opened])
        self.assertEqual(result.verification.name, "PASS", result.output)
        self.assertEqual(clicks[-1], (202, 619))                       # the 4th row, not the top one
        self.assertEqual(typed, ["AK"])

    def unreadable_ub(self):
        results = self.lines(("Pushkar Dubey ICMME Team JU...", (190, 327, 488, 346)), ("", (189, 612, 215, 627)))
        results[-1]["green"] = True
        searched = [{"text": "x", "rect": (538, 148, 553, 163)}] + results
        return searched, searched + [{"text": "", "rect": (620, 30, 660, 50)}]

    def test_chat_already_open_is_confirmed_by_being_the_highlighted_row(self):
        """Live 2026-10-04: a second send to Ak right after the first failed (its row was already selected)."""
        searched, opened = self.unreadable_ub()
        result, typed, _clicks, _keys = self.run_flow(
            [self.BASE, searched, opened], row_light=lambda _shot, box: 50 if box[1] == 612 else 30)
        self.assertEqual(result.verification.name, "PASS", result.output)
        self.assertEqual(typed, ["AK"])

    def test_unreadable_header_with_no_distinct_selected_row_sends_nothing(self):
        searched, opened = self.unreadable_ub()
        result, typed, _clicks, _keys = self.run_flow([self.BASE, searched, opened], dry_run=False,
                                                     row_light=lambda _shot, _box: 50)   # every row looks alike
        self.assertEqual(result.verification.name, "FAIL")
        self.assertIn("nothing was sent", result.output["error"])
        self.assertEqual(typed, ["AK"])                                           # never the message

    def test_wrong_chat_means_nothing_is_typed_or_sent(self):
        searched = self.lines(("AK", (120, 145, 140, 160)), ("AK", (190, 330, 215, 347)))
        wrong = searched + [{"text": "Mata Shri", "rect": (620, 30, 700, 50)}]
        result, typed, _clicks, _keys = self.run_flow([self.BASE, searched, wrong], dry_run=False)
        self.assertEqual(result.verification.name, "FAIL")
        self.assertIn("nothing was sent", result.output["error"])
        self.assertEqual(typed, ["AK"])

    def test_missing_search_box_or_chat_types_nothing(self):
        bare = [{"text": "Yesterday", "rect": (493, 425, 558, 440)}]
        result, typed, _clicks, _keys = self.run_flow([bare], dry_run=False)
        self.assertEqual(result.verification.name, "FAIL")
        self.assertEqual(typed, [])
        searched = self.lines(("AK", (120, 145, 140, 160)))     # search ran, but no chat row matches
        result, typed, _clicks, keys = self.run_flow([self.BASE, searched], dry_run=False)
        self.assertIn("No WhatsApp chat is named exactly", result.output["error"])
        self.assertEqual(typed, ["AK"])
        self.assertIn([0x1B], keys)                            # the search is cleared again


class HeaderReadTests(unittest.TestCase):
    """Live 2026-10-06: plain OCR read the header "Pita Shri" as "Shi"; the enlarged read gets it right."""

    def test_enlarged_read_confirms_the_name_and_a_different_name_does_not(self):
        import numpy as np
        from unittest.mock import patch
        from chutku import vision
        from chutku.tools import apps_extra
        shot = vision.Shot(np.zeros((10, 10, 3), np.uint8), 0, 0, 10, 10)
        with patch.object(vision, "read_region", return_value=[{"text": "Pita Shri"}]):
            self.assertTrue(apps_extra._header_reads(shot, (0, 0, 10, 10), "Pita Shri"))
        with patch.object(vision, "read_region", return_value=[{"text": "JUET 2023-27"}]):
            self.assertFalse(apps_extra._header_reads(shot, (0, 0, 10, 10), "Pita Shri"))
        with patch.object(vision, "read_region", side_effect=OSError("ocr")):
            self.assertFalse(apps_extra._header_reads(shot, (0, 0, 10, 10), "Pita Shri"))


class OpenChatTests(unittest.TestCase):
    def tearDown(self):
        from chutku.tools import apps_extra
        apps_extra.LAST_CHAT.update(app=None, to=None, at=0.0)   # never leak an "open chat" into other tests

    def test_open_chat_keeps_it_open_resolves_nicknames_and_remembers_it(self):
        from unittest.mock import patch
        from chutku.tools import apps_extra
        from chutku.tools.registry import ToolResult, Verification
        calls = []

        def fake(name, text, *, dry_run=False, keep_open=False):
            calls.append((name, text, dry_run, keep_open))
            return ToolResult({"chat_confirmed": True}, Verification.PASS)
        apps_extra.LAST_CHAT.update(app=None, to=None, at=0.0)
        with patch.object(apps_extra, "_send_to_named_chat", side_effect=fake), \
                patch.object(apps_extra, "recipient", return_value=("", "AK", "AK")):
            result = apps_extra._open_chat({"app": "whatsapp", "to": "mammi"}, None)
        self.assertEqual(result.verification, Verification.PASS)
        self.assertEqual(calls, [("AK", "", True, True)])                 # opened, never typed, Esc not pressed
        self.assertEqual(apps_extra.recent_chat(), ("whatsapp", "AK"))

    def test_failed_open_remembers_nothing(self):
        from unittest.mock import patch
        from chutku.tools import apps_extra
        from chutku.tools.registry import ToolResult, Verification
        apps_extra.LAST_CHAT.update(app=None, to=None, at=0.0)
        with patch.object(apps_extra, "_send_to_named_chat",
                          return_value=ToolResult({"error": "No WhatsApp chat is named exactly 'Zz'"}, Verification.FAIL)), \
                patch.object(apps_extra, "recipient", return_value=None):
            result = apps_extra._open_chat({"app": "whatsapp", "to": "Zz"}, None)
        self.assertEqual(result.verification, Verification.FAIL)
        self.assertIsNone(apps_extra.recent_chat())


class WhatsAppViewTests(unittest.TestCase):
    RECT = (-9, -9, 1929, 1029)

    def view(self, *titles):
        from chutku.tools.apps_extra import whatsapp_view
        lines = [{"text": text, "rect": rect} for text, rect in titles]
        return whatsapp_view(lines, self.RECT)

    def test_reads_which_view_is_open(self):
        # live 2026-10-04: the owner's WhatsApp was on Archived, which has no chat search bar
        self.assertEqual(self.view(("WhatsApp", (56, 16, 125, 31)), ("Archived", (108, 77, 230, 98))), "Archived")
        self.assertEqual(self.view(("Chats", (108, 77, 177, 98))), "Chats")
        self.assertEqual(self.view(("Locked chats", (108, 77, 260, 98))), "Locked chats")
        self.assertEqual(self.view(("Calls", (108, 77, 170, 98))), "Calls")
        self.assertIsNone(self.view(("Shambhavi", (600, 60, 800, 90))))     # chat headers are not views
        # live 2026-10-04: WhatsApp on the PC had been logged out (QR login screen)
        self.assertEqual(self.view(("Log in to WhatsApp", (513, 345, 830, 385)),
                                   ("Scan the QR code with your phone's camera", (560, 440, 1000, 465))), "Logged out")

    def test_logged_out_whatsapp_is_reported_at_once_and_nothing_is_clicked(self):
        flow = NamedChatTests()
        login = [{"text": "Log in to WhatsApp", "rect": (513, 345, 830, 385)},
                 {"text": "Scan the QR code with your phone's camera", "rect": (560, 440, 1000, 465)}]
        result, typed, clicks, keys = flow.run_flow([login], dry_run=False)
        self.assertIn("logged out", result.output["error"])
        self.assertEqual((typed, clicks, keys), ([], [], []))

    def test_not_found_mentions_locked_chats(self):
        flow = NamedChatTests()
        searched = flow.lines(("AK", (120, 145, 140, 160)))
        result, typed, _clicks, _keys = flow.run_flow([flow.BASE, searched], dry_run=False)
        self.assertIn("Locked chats", result.output["error"])
        self.assertEqual(typed, ["AK"])


class ReadChatTests(unittest.TestCase):
    RECT = (-9, -9, 1929, 1029)
    PANE = 577

    def lines(self, *items):
        return [{"text": text, "rect": rect} for text, rect in items]

    def test_sides_joined_bubbles_times_dates_and_photo_text(self):
        from chutku.tools.apps_extra import chat_messages
        lines = self.lines(
            ("Today", (1220, 300, 1270, 316)),                       # centred date separator
            ("kaise ho beta", (600, 340, 760, 358)),                  # them
            ("khana khaya? 6:21 pm", (600, 362, 830, 380)),          # same bubble, time dropped
            ("hi 4:14 pm", (1750, 420, 1860, 438)),                   # you
            ("- 473226", (1750, 560, 1784, 566)),                     # tiny text inside a photo: skipped
            ("haan papa 4:20 pm", (600, 600, 780, 618)),              # them
            (":14 pm", (1790, 640, 1850, 658)),                        # cut-off timestamp (live): not a message
            ("@", (1860, 640, 1870, 658)))
        self.assertEqual(chat_messages(lines, self.RECT, self.PANE), [
            {"from": "them", "text": "kaise ho beta khana khaya?"},
            {"from": "you", "text": "hi"},
            {"from": "them", "text": "haan papa"}])

    def test_phrases(self):
        from chutku.message_intent import parse_read_chat
        self.assertEqual(parse_read_chat("kya mammi ne reply kiya"), {"app": "whatsapp", "to": "mammi"})
        self.assertEqual(parse_read_chat("पिता श्री ने क्या बोला"), {"app": "whatsapp", "to": "pita shri"})
        self.assertIsNone(parse_read_chat("what did he say"))

    def test_read_chat_is_treated_as_untrusted_private_content(self):
        from chutku.agent_loop import PRIVATE_TOOLS, TAINTING_TOOLS
        self.assertIn("message.read_chat", TAINTING_TOOLS)     # a message saying "delete my files" needs a click
        self.assertIn("message.read_chat", PRIVATE_TOOLS)

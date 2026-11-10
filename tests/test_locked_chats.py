"""WhatsApp Locked chats (owner 2026-11-10: "Locked chat open krna jo bola usko dhang se search krna brain ka istemaal
krke"): Chutku opens Locked chats, the OWNER types the secret code (never Chutku), then the chat is found by its exact,
first, closest or brain-picked name and remembered as locked."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.tools import apps_extra
from chutku.tools.registry import ToolResult, Verification

RECT = (-9, -9, 1929, 1029)   # the owner's maximized WhatsApp (see test_apps_extra.NamedChatTests)
CHATS = [{"text": "Chats", "rect": (108, 77, 177, 98)}, {"text": "11:58 am", "rect": (497, 331, 558, 342)}]
LOCKED = [{"text": "Locked chats", "rect": (108, 77, 230, 98)}, {"text": "KitKat", "rect": (189, 326, 260, 347)},
          {"text": "11:58 am", "rect": (497, 331, 558, 342)}]
PROMPT = CHATS + [{"text": "Enter your secret code", "rect": (800, 400, 1100, 430)},
                  {"text": "Cancel", "rect": (850, 600, 920, 620)}]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class UnlockTests(unittest.TestCase):
    def unlock(self, screens, wait=60.0):
        clock, seen, clicks, escs, notes = Clock(), iter(screens), [], [], []
        last = {"screen": screens[-1]}

        def look():
            last["screen"] = next(seen, last["screen"])
            return last["screen"]
        with patch("chutku.tools.desktop_controls.type_unicode", side_effect=AssertionError("typed")), \
                patch("chutku.tools.desktop_controls.press_combo", side_effect=AssertionError("key")), \
                patch.object(apps_extra, "_scale", return_value=1.25):
            lines, error = apps_extra._unlock_locked_chats(
                5, RECT, look, wait=wait, click=lambda x, y: clicks.append((x, y)), esc=lambda: escs.append(1),
                notify=lambda title, text: notes.append(text), sleep=clock.sleep, clock=clock)
        return lines, error, clicks, escs, notes

    def test_waits_while_the_owner_types_the_code_and_types_nothing_itself(self):
        lines, error, clicks, escs, notes = self.unlock([PROMPT, PROMPT, PROMPT, LOCKED])
        self.assertIsNone(error)
        self.assertEqual(lines, LOCKED)
        self.assertEqual(clicks, [(38, 485)])                  # the rail icon, once; never the code box or Continue
        self.assertEqual(notes, [apps_extra.LOCKED_ASK])       # asked once, not on every look
        self.assertEqual(escs, [])

    def test_the_code_box_closed_without_unlocking_stops_cleanly(self):
        lines, error, _clicks, escs, _notes = self.unlock([PROMPT, CHATS])
        self.assertIsNone(lines)
        self.assertIn("stayed locked", error)
        self.assertIn("Nothing was typed or sent", error)
        self.assertEqual(escs, [])

    def test_no_unlock_in_time_closes_the_code_box_and_fails_closed(self):
        lines, error, _clicks, escs, notes = self.unlock([PROMPT], wait=5)
        self.assertIsNone(lines)
        self.assertIn("not unlocked within 5 seconds", error)
        self.assertEqual((escs, len(notes)), ([1], 1))

    def test_a_click_that_opened_neither_the_code_box_nor_the_list_stops(self):
        lines, error, _clicks, escs, notes = self.unlock([CHATS])
        self.assertIsNone(lines)
        self.assertIn("not where expected", error)
        self.assertEqual((escs, notes), ([1], []))

    def test_a_locked_list_still_behind_the_code_box_is_not_taken_as_unlocked(self):
        """The list's title may already read 'Locked chats' under the code box: only a list WITHOUT the box counts."""
        behind = LOCKED + PROMPT[2:]
        lines, error, _clicks, _escs, notes = self.unlock([behind, behind, LOCKED])
        self.assertEqual((lines, error, len(notes)), (LOCKED, None, 1))


def rows(*names):
    return [{"text": name, "rect": (189, 300 + 60 * i, 480, 340 + 60 * i), "highlight": 0.0}
            for i, name in enumerate(names)]


class PickTests(unittest.TestCase):
    def pick(self, listed, name, brain=None):
        asked = []

        def ask(wanted, names):
            asked.append((wanted, names))
            return brain
        row, how = apps_extra.pick_chat_row(rows(*listed), name, ask=ask)
        return (row["text"] if row else None), how, asked

    def test_exact_first_name_and_closest_name_need_no_model(self):
        self.assertEqual(self.pick(["Mummy", "KitKat"], "kitkat")[:2], ("KitKat", "exact"))
        self.assertEqual(self.pick(["Kritika Raj 2nd JUET", "UB"], "Kritika")[:2], ("Kritika Raj 2nd JUET", "first name"))
        self.assertEqual(self.pick(["KitKat", "UB"], "Kit Kat")[:2], ("KitKat", "exact"))   # spaces never count
        self.assertEqual(self.pick(["Tech Clubs (All)", "UB"], "tech clubs")[:2], ("Tech Clubs (All)", "first name"))
        self.assertEqual(self.pick(["KitKat", "UB"], "Kitkatt")[:2], ("KitKat", "close"))   # misheard
        self.assertEqual(self.pick(["KitKat"], "kitkat")[2], [])                            # no cloud call

    def test_the_brain_picks_only_a_listed_name_from_names_alone(self):
        self.assertEqual(self.pick(["Billu", "Golu"], "मेरी बिल्ली", brain="Billu")[:2], ("Billu", "brain"))
        _row, _how, asked = self.pick(["Billu", "Golu"], "मेरी बिल्ली", brain="Billu")
        self.assertEqual(asked, [("मेरी बिल्ली", ["Billu", "Golu"])])   # names only, never a message
        self.assertEqual(self.pick(["Billu", "Golu"], "Chintu", brain="Chintu (made up)")[:2], (None, "not found"))
        self.assertEqual(self.pick(["Billu", "Golu"], "Chintu", brain=None)[:2], (None, "not found"))

    def test_two_chats_with_the_name_open_nothing(self):
        self.assertEqual(self.pick(["KitKat", "KitKat"], "KitKat")[:2], (None, "several"))

    def test_the_brain_answer_is_checked_against_the_list(self):
        with patch("chutku.providers.ask", return_value=({"pick": "Golu"}, {})):
            self.assertEqual(apps_extra._ask_brain_for_chat("golu bhai", ["Billu", "Golu"]), "Golu")
        with patch("chutku.providers.ask", return_value=({"pick": "Someone else"}, {})):
            self.assertIsNone(apps_extra._ask_brain_for_chat("x", ["Billu", "Golu"]))
        with patch("chutku.providers.ask", side_effect=RuntimeError("no key")):
            self.assertIsNone(apps_extra._ask_brain_for_chat("x", ["Billu"]))


class LockedSendTests(unittest.TestCase):
    def test_found_chat_is_confirmed_sent_and_remembered_as_locked(self):
        from chutku import vision
        clicks = []
        with tempfile.TemporaryDirectory():
            with patch.object(apps_extra, "_unlock_locked_chats", return_value=(LOCKED, None)), \
                    patch.object(apps_extra, "_result_rows", return_value=rows("KitKat", "UB")), \
                    patch.object(vision, "click_at", side_effect=lambda x, y: clicks.append((x, y))), \
                    patch.object(apps_extra, "_open_pane_for", return_value=563), \
                    patch.object(apps_extra, "_remember_chat_header"), \
                    patch.object(apps_extra, "_finish_send",
                                 return_value=ToolResult({"to": "KitKat"}, Verification.PASS)) as finish, \
                    patch.object(apps_extra.time, "sleep"), \
                    patch("chutku.mind.default") as default:
                result, how = apps_extra._send_in_locked_chats("kitkatt", "hello", 5, RECT, lambda: LOCKED,
                                                               {"shot": None}, dry_run=False, keep_open=False)
        self.assertEqual((result.verification, how), (Verification.PASS, "close"))
        self.assertEqual(clicks, [(334, 320)])                         # the KitKat row
        self.assertEqual(finish.call_args.args[:2], ("KitKat", "hello"))
        default.return_value.remember_person.assert_called_once_with("KitKat", whatsapp="KitKat",
                                                                     whatsapp_locked=True, aliases=["kitkatt"])
        self.assertTrue(result.output["locked_chat"])

    def test_a_chat_missing_from_locked_chats_too_is_reported_not_guessed(self):
        with patch.object(apps_extra, "_unlock_locked_chats", return_value=(LOCKED, None)), \
                patch.object(apps_extra, "_result_rows", return_value=rows("KitKat")), \
                patch.object(apps_extra, "_ask_brain_for_chat", return_value=None), \
                patch("chutku.vision.click_at", side_effect=AssertionError("clicked a guess")):
            result, how = apps_extra._send_in_locked_chats("Chintu", "hello", 5, RECT, lambda: LOCKED,
                                                           {"shot": None}, dry_run=False, keep_open=False)
        self.assertEqual((result, how), (None, "not found"))

    def test_the_mind_remembers_a_locked_chat(self):
        from chutku import mind
        with tempfile.TemporaryDirectory() as temp, patch.object(mind, "default", return_value=mind.Mind(temp)):
            mind.default().remember_person("KitKat", whatsapp="KitKat", whatsapp_locked=True)
            self.assertTrue(apps_extra._locked_person("kitkat"))
            self.assertFalse(apps_extra._locked_person("UB"))


if __name__ == "__main__":
    unittest.main()

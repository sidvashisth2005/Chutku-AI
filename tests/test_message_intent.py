import unittest

from chutku.message_intent import parse_send
from chutku.quick_intents import quick_proposal

W = "whatsapp"


class MessageIntentTests(unittest.TestCase):
    def test_owner_session_goals_resolve_instantly(self):
        """The exact goals the voice model produced on 2026-10-03, which used to go to the slow planner."""
        for goal in ('In WhatsApp, find the chat titled "AK" and send the message "hi" to it.',
                     'Open WhatsApp and send the message "Hi" to the user named AK.',
                     'Retry sending the message "Hi" to AK on WhatsApp.'):
            parsed = parse_send(goal)
            self.assertEqual((parsed["app"], parsed["to"], parsed["text"].casefold()), (W, "AK", "hi"), goal)
            step = quick_proposal(goal, apps=[])["next_steps"][0]
            self.assertEqual(step["tool"], "message.send", goal)

    def test_typed_english_and_hinglish(self):
        cases = {
            "send hi to AK on whatsapp": (W, "AK", "hi"),
            'send a message "good morning" to Mummy on WhatsApp': (W, "Mummy", "good morning"),
            "message AK on whatsapp saying hi there": (W, "AK", "hi there"),
            "whatsapp AK: hi": (W, "AK", "hi"),
            "AK ko whatsapp pe hi bhejo": (W, "AK", "hi"),
            "AK ko kal milte hain bhej do whatsapp pe": (W, "AK", "kal milte hain"),
            'Send the message "Hello" to "Pita Shri" on WhatsApp': (W, "Pita Shri", "Hello"),
            'Send "see you at 5" to the contact named Rahul Sharma on WhatsApp': (W, "Rahul Sharma", "see you at 5"),
            "send hi to ak on telegram": ("telegram", "ak", "hi"),
        }
        for text, expected in cases.items():
            parsed = parse_send(text)
            self.assertEqual((parsed["app"], parsed["to"], parsed["text"]), expected, text)

    def test_unclear_requests_are_left_to_the_model(self):
        for text in ("open whatsapp", "what is whatsapp", "send hi", "send a message to AK on whatsapp",
                     "send it to AK on whatsapp", "send hi to AK"):
            self.assertIsNone(parse_send(text), text)


if __name__ == "__main__":
    unittest.main()

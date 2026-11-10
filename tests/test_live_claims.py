"""Live conversation must not claim PC work it did not start (2026-10-11: "us par click kar rahi hoon ... play button
pe click kar diya" with no tool call; nothing happened), and the owner's real sentences route instantly."""
import unittest
from unittest.mock import patch

from chutku.quick_intents import quick_proposal
from chutku.voice import heard
from chutku.voice.live import LiveConversation
from tests.test_heard import FakeServer, chunk

APPS = [{"name": "Spotify", "app_id": "S"}]


def say(text):
    return {"serverContent": {"outputTranscription": {"text": text}}}


def owner(text):
    return {"serverContent": {"inputTranscription": {"text": text}}}


DONE = {"serverContent": {"turnComplete": True}}


class ClaimTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.live = LiveConversation(self.server, "key", audio=False)
        self.live._follow = lambda *_: None
        self.live._task_running = lambda: False
        patcher = patch.object(heard, "log_heard", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        for _ in range(30):                     # 3 s of clear speech from the owner
            self.live.gate.feed(chunk(0.2))

    def turn(self, request, reply):
        self.live.handle(owner(request))
        self.live.handle(say(reply))
        return self.live.handle(DONE)

    def test_a_claim_without_a_task_starts_the_owners_request(self):
        sent = self.turn("Screen par dekh meri after party playlist dikh rahi hogi, uss par click kar.",
                         "Haan, samajh gayi! Us par click kar rahi hoon.")
        self.assertEqual(self.server.tasks, ["Screen par dekh meri after party playlist dikh rahi hogi, uss par click kar."])
        note = sent["clientContent"]["turns"][0]["parts"][0]["text"]
        self.assertIn("Wait for the [Task update]", note)

    def test_set_karti_hoon_is_a_claim_too(self):
        # live 2026-11-07: "Done! 6:30 ka alarm ... abhi set karti hoon" and no alarm was ever set
        request = 'और मुझे 6:30 पर मेरा एक अलार्म बजना चाहिए। अलार्म का टाइटल "jaldi kar le bhai"'
        sent = self.turn(request, 'Done! 6:30 ka alarm, title "jaldi kar le bhai", abhi set karti hoon.')
        self.assertEqual(self.server.tasks, [request])
        self.assertIn("Wait for the [Task update]", sent["clientContent"]["turns"][0]["parts"][0]["text"])

    def test_the_turn_that_started_a_task_is_remembered_for_the_log(self):
        self.turn("Kya haal hai?", "Badhiya!")                                        # owner turn 0: chat
        self.turn("Bhai Spotify chalu kar.", "Spotify khol rahi hoon.")              # turn 1: claim -> task
        self.live._running = lambda: []                                               # the first task finished
        for _ in range(30):                                                           # the owner speaks again
            self.live.gate.feed(chunk(0.2))
        self.live.handle(owner("WhatsApp kholo"))                                     # turn 2: the model calls it
        self.live.dispatch("do_task", {"goal": "open whatsapp"})
        self.assertEqual(self.live.tasked_turns, {1, 2})

    def test_no_double_start_when_the_model_did_call_the_task(self):
        self.live.handle(owner("Bhai Spotify chalu kar."))
        self.live.dispatch("do_task", {"goal": "open spotify"})
        self.live.handle(say("Abhi Spotify open kar rahi hoon."))
        self.assertIsNone(self.live.handle(DONE))
        self.assertEqual(self.server.tasks, ["open spotify"])

    def test_an_offer_or_plain_talk_is_not_a_claim(self):
        self.assertIsNone(self.turn("App to band ho gaya hai", "Main usko fir se open kar deti hoon. Karoon?"))
        self.assertIsNone(self.turn("kaisi ho", "Main badhiya hoon, tum batao!"))
        self.assertEqual(self.server.tasks, [])

    def test_nothing_starts_while_saying_goodbye(self):
        self.live.dispatch("end_conversation", {})
        self.assertIsNone(self.turn("bas bye", "Theek hai, band kar rahi hoon."))
        self.assertEqual(self.server.tasks, [])

    def test_done_claim_while_the_task_failed_is_corrected(self):
        # 2026-10-06: "Ho gaya, Bluetooth band" -> owner: "Bluetooth band nahin hua hai".
        self.live._snapshot = lambda: {"status": "failed", "goal": "turn off bluetooth", "steps": []}
        sent = self.turn("Bluetooth band karo", "Ho gaya, Bluetooth band kar diya!")
        note = sent["clientContent"]["turns"][0]["parts"][0]["text"]
        self.assertIn("NOTHING is confirmed done", note)
        self.assertIn("failed", note)
        self.assertEqual(self.live.false_claims, 1)

    def test_done_claim_after_a_verified_task_is_fine(self):
        self.live._snapshot = lambda: {"status": "done", "goal": "turn off bluetooth", "steps": []}
        self.live.task_this_turn = True
        self.assertIsNone(self.turn("Bluetooth band karo", "Ho gaya, Bluetooth band ho gaya."))
        self.assertEqual(self.live.false_claims, 0)

    def test_done_claim_with_no_task_at_all_is_corrected(self):
        self.live._snapshot = lambda: None
        self.live.ending_at = None
        self.live.said_this_turn = "Ho gaya!"
        sent = self.live._claimed_success()
        self.assertIn("no task was run", sent["clientContent"]["turns"][0]["parts"][0]["text"])


class PersonaRuleTests(unittest.TestCase):
    def test_the_voice_persona_stays_silent_on_noise_and_ends_without_a_question_tail(self):
        from chutku import identity
        from chutku.voice.live import PERSONA, _BASE_PERSONA, personalize
        for persona in (PERSONA, personalize(_BASE_PERSONA, {**identity.DEFAULTS, "ASSISTANT_NAME": "Mitra",
                                                              "ASSISTANT_GENDER": "male",
                                                              "ASSISTANT_LANGUAGE": "english"})):
            self.assertIn("stay silent and do not reply at all", persona)
            self.assertIn('never with "aur kuch?"', persona)
            self.assertIn('"haan ya na?"', persona)


class RoutingTests(unittest.TestCase):
    def steps(self, goal, verified=True):
        with patch("chutku.apps.lab.verified", return_value=verified):
            proposal = quick_proposal(goal, apps=APPS)
        return [(s["tool"], s["arguments"]) for s in proposal["next_steps"]] if proposal else None

    def test_owner_sentences_from_the_live_log(self):
        self.assertEqual(self.steps("Bhai Spotify chalu kar."), [("apps.launch", {"name": "Spotify"})])
        self.assertEqual(self.steps("Screen par dekh meri after party playlist dikh rahi hogi already, uss par click kar."),
                         [("app.spotify.play_playlist", {"name": "after party"})])

    def test_unverified_playlist_uses_the_screen_tool_and_songs_stay_songs(self):
        got = self.steps("Screen par dekh meri after party playlist dikh rahi hogi, uss par click kar.", verified=False)
        self.assertEqual(got[0][0], "screen.act_on_visible")
        got = self.steps("screen pe dekh after party song dikh raha hai usko play karo")
        self.assertEqual(got, [("screen.act_on_visible", {"name": "after party", "action": "play", "kind": "song",
                                                          "app": "spotify"})])


if __name__ == "__main__":
    unittest.main()

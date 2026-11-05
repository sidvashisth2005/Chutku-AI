"""Every instant reply and answer must read as finished, or the model is asked to "continue" a done task
(live 2026-10-04: "Playing Latent season 2 ..." made the model try to click the video player)."""
import unittest

from chutku.agent_loop import _IN_PROGRESS
from chutku.quick_intents import QUICK_ANSWERS, quick_proposal

PHRASES = ["play lofi on youtube", "play Latent season 2 latest episode on youtube in brave", "open spotify",
           "open youtube.com in brave browser", "search lofi on youtube in brave", "next song", "pause", "mute",
           "volume up", "set volume to 30", "switch to dark mode", "AK is my mammi", "note: buy milk",
           "remind me in 20 minutes to drink water", "brave browser kholo", "lock my pc"]


class FinishedRepliesTests(unittest.TestCase):
    def test_instant_replies_never_look_in_progress(self):
        apps = [{"name": "Spotify", "app_id": "S"}, {"name": "Brave", "app_id": "B"}]
        for phrase in PHRASES:
            proposal = quick_proposal(phrase, apps=apps)
            self.assertIsNotNone(proposal, phrase)
            self.assertIsNone(_IN_PROGRESS.search(proposal["reply"] or ""), (phrase, proposal["reply"]))

    def test_media_answer_reads_finished(self):
        text = QUICK_ANSWERS["media.status"]({"title": "Song", "artist": "Band"})
        self.assertIsNone(_IN_PROGRESS.search(text), text)


if __name__ == "__main__":
    unittest.main()

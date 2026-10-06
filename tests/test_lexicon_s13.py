"""One Hinglish vocabulary for every instant parser (master plan S13)."""
import unittest

from chutku.quick_intents import quick_proposal


def tools(goal):
    proposal = quick_proposal(goal, apps=[{"name": "Spotify", "app_id": "spotify"}])
    return None if proposal is None else [s["tool"] for s in proposal["next_steps"]]


class LexiconTests(unittest.TestCase):
    def test_the_same_fillers_work_in_every_parser(self):
        # each parser had its own list: "bhai ..." worked in some and not in others
        self.assertEqual(tools(r"bhai delete D:\notes\old.txt"), tools(r"delete D:\notes\old.txt"))
        self.assertEqual(tools("bhai open spotify please"), ["apps.launch"])
        self.assertEqual(tools("zara kitne baje hain abhi"), ["system.get_time"])
        self.assertEqual(tools("yaar mute karo na"), tools("mute karo"))

    def test_fillers_never_become_part_of_a_name(self):
        proposal = quick_proposal("open spotify na", apps=[{"name": "Spotify", "app_id": "spotify"}])
        self.assertEqual(proposal["next_steps"][0]["arguments"]["name"], "Spotify")


if __name__ == "__main__":
    unittest.main()

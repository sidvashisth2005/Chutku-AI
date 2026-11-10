"""App Mastery 2: the survey never presses consequential or outside-reaching elements, and a page becomes an action
only with proof that it opened (an element only that page shows)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import app_survey  # noqa: E402
import make_ui_atlases  # noqa: E402
from chutku.apps import atlas as atlas_module  # noqa: E402


def element(name, role="button", states=()):
    return {"name": name, "role": role, "states": list(states), "actions": ["click"]}


class SurveyTests(unittest.TestCase):
    def test_never_presses_consequential_or_outside_reaching_names(self):
        for name in ("Send", "Delete", "Sign out", "Uninstall", "Reset", "Turn off Bluetooth", "Save", "Print",
                     "Close Calculator", "Minimize", "Share", "Play", "New note", "Paste", "Clear all memory"):
            self.assertFalse(app_survey.touchable(element(name)), name)
        self.assertFalse(app_survey.touchable(element("Scientific Calculator", states=["disabled"])))
        self.assertFalse(app_survey.touchable(element("")))
        for name in ("Scientific Calculator", "Alarm", "Brushes", "View", "Bluetooth & devices"[:6]):
            self.assertTrue(app_survey.touchable(element(name)), name)

    def test_a_page_is_an_action_only_with_proof_it_opened(self):
        uimap = {"app": "clock", "start_menu": "Clock", "at": "2026-11-10T11:00:00",
                 "window": {"exe": "ClockApp.exe", "title": "Clock"},
                 "pages": {"home": {"elements": ["button:Start"]},
                           "Alarm": {"via": ["Alarm"], "delivery": "delivered_unverified",
                                     "new_elements": ["button:Add an alarm", "button:Start"]},
                           "Stopwatch": {"via": ["Stopwatch"], "delivery": "delivered_unverified", "new_elements": []},
                           "Timer": {"via": ["Timer"], "error": "STALE_REF"}}}
        atlas = make_ui_atlases.build(uimap)
        atlas_module.validate(atlas)
        self.assertEqual([a["id"] for a in atlas["actions"]], ["alarm"])          # nothing changed on Stopwatch
        action = atlas["actions"][0]
        self.assertEqual(action["steps"], [{"launch": "behind"}, {"do": "Alarm", "action": "click"}])
        self.assertEqual(action["check"], {"has_element": "Add an alarm"})
        self.assertIn("clock mein alarm kholo", action["phrases"])
        self.assertTrue(atlas_module.background_only(action))

    def test_no_page_with_proof_means_no_atlas(self):
        self.assertIsNone(make_ui_atlases.build({"app": "calc", "start_menu": "Calculator", "pages": {
            "home": {"elements": []}, "Scientific Calculator": {"new_elements": []}}}))


if __name__ == "__main__":
    unittest.main()

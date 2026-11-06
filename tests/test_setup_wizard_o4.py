"""O4 (2026-11-06): first-run setup asks four skippable questions and only stores what the owner gave."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku import setup_wizard
from chutku.core.preferences import Preferences
from chutku.mind import Mind


class SetupTests(unittest.TestCase):
    def run_with(self, answers, key=""):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        replies = iter(answers)
        done = setup_wizard.run(base, ask=lambda _q: next(replies), secret=lambda _q: key, out=lambda *_: None,
                                mic_check=lambda _b: {"peak": 0.3, "heard": True})
        return base, done

    def test_name_key_mic_and_mode_are_stored_where_chutku_reads_them(self):
        with patch("chutku.providers.store_key") as store:
            base, done = self.run_with(["Asha", "groq", "", "3"], key="gsk_test")
        store.assert_called_once_with("groq", "gsk_test")
        self.assertEqual(done, {"name": "Asha", "brain_key": "groq", "microphone": {"peak": 0.3, "heard": True},
                                "mode": "auto_edits"})
        self.assertEqual(Preferences(base).load()["handsfree_mode"], "auto_edits")
        self.assertIn("Asha", str(Mind(base).snapshot() if hasattr(Mind(base), "snapshot") else
                                 (base / "data" / "mind.json").read_text(encoding="utf-8")))

    def test_skipping_everything_changes_only_the_default_mode(self):
        with patch("chutku.providers.store_key") as store, patch("chutku.cloud_planner.store_key") as gem:
            base, done = self.run_with(["", "", "n", ""])
        store.assert_not_called()
        gem.assert_not_called()
        self.assertEqual(done, {"mode": "auto_safe"})   # Enter = 2: safe things alone, ask before changes

    def test_an_empty_key_is_not_stored(self):
        with patch("chutku.providers.store_key") as store:
            _base, done = self.run_with(["", "groq", "n", "9"], key="   ")
        store.assert_not_called()
        self.assertNotIn("mode", done)   # an invalid choice changes nothing


if __name__ == "__main__":
    unittest.main()

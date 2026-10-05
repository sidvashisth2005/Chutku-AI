import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


class PhraseCoverageTests(unittest.TestCase):
    def test_every_real_phrasing_resolves_instantly_to_the_right_tool(self):
        import check_phrases
        misses, _slowest = check_phrases.run()
        self.assertEqual(misses, [])


if __name__ == "__main__":
    unittest.main()

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.evidence import CRITICAL_FILES, source_digest


class EvidenceTests(unittest.TestCase):
    def test_digest_tracks_code_benchmarks_and_critical_configuration(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            for directory in ("chutku", "tests", "scripts", "benchmarks", "models"):
                directory_path = base / directory
                directory_path.mkdir()
                (directory_path / "tracked.py").write_text("one", encoding="utf-8")
            for relative in CRITICAL_FILES:
                path = base / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("one", encoding="utf-8")
            original = source_digest(base)
            for relative in CRITICAL_FILES:
                path = base / relative
                path.write_text("two", encoding="utf-8")
                self.assertNotEqual(source_digest(base), original, relative)
                path.write_text("one", encoding="utf-8")
            (base / "benchmarks/tracked.py").write_text("two", encoding="utf-8")
            self.assertNotEqual(source_digest(base), original)


if __name__ == "__main__":
    unittest.main()

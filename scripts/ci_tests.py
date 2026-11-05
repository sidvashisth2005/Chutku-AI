r"""Run the unit tests on a CI machine (GitHub's Windows runners), and only there.

GitHub's Windows runners run every job as Administrator, and Chutku refuses every action while elevated (that is a
safety rule: chutku/core/elevation.py). Without this launcher almost every runtime test is DENIED in CI.

Here, and only here, the token query reports "not elevated". The product code has no bypass. The tests that force
`is_elevated` to True (tests/test_elevation.py and others) still prove the refusal, because their patches take
precedence while they run. On a normal PC run the tests directly:
    .venv\Scripts\python.exe -m unittest discover -s tests
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.core import elevation  # noqa: E402

if __name__ == "__main__":
    with patch.object(elevation, "_query_token", return_value=False):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT / "tests"))
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

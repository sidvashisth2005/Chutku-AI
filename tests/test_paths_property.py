"""Property-based check of the protected-zone guard (the reason hypothesis is pinned in requirements.lock)."""
import os
from pathlib import Path
import unittest

from hypothesis import given, settings, strategies as st

from chutku.core import paths

# Names that are valid as one Windows path part.
PART = st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters=" -_."),
               min_size=1, max_size=12).map(lambda s: s.strip(" .") or "x")


def _zones():
    zones = [os.environ.get("SystemRoot", r"C:\Windows"), os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramData", r"C:\ProgramData"), paths.appdata_root()]
    return [z for z in zones if z]


class ProtectedZoneProperties(unittest.TestCase):
    @settings(max_examples=150, deadline=None)
    @given(zone=st.sampled_from(_zones()), parts=st.lists(PART, min_size=1, max_size=4))
    def test_nothing_inside_a_system_or_app_zone_is_silently_writable(self, zone, parts):
        target = Path(zone).joinpath(*parts)
        if any(target.resolve().as_posix().casefold().startswith(Path(e).resolve().as_posix().casefold())
               for e in (paths.home() / "sandbox", Path(__import__("tempfile").gettempdir()))):
            return   # Chutku's own scratch and %TEMP% (inside AppData) are the documented exceptions
        # WA1 (owner 2026-11-08): Windows' own folder is refused; an app's own files (Program Files, ProgramData,
        # AppData) ask the first time. Either way, never a silent change.
        if zone == os.environ.get("SystemRoot", r"C:\Windows"):
            self.assertIsNotNone(paths.protection_reason(target), str(target))
        else:
            self.assertTrue(paths.protection_reason(target) or paths.sensitive_reason(target), str(target))

    @settings(max_examples=100, deadline=None)
    @given(parts=st.lists(PART, min_size=1, max_size=4))
    def test_case_changes_do_not_escape(self, parts):
        zone = os.environ.get("SystemRoot", r"C:\Windows")
        for variant in (zone.upper(), zone.lower(), zone.swapcase()):
            self.assertIsNotNone(paths.protection_reason(Path(variant).joinpath(*parts)))


if __name__ == "__main__":
    unittest.main()

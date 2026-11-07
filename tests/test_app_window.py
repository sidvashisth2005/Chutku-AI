"""PC check 2026-11-07: an installed Chutku opens its own app window, a checkout keeps the browser tab."""
import unittest
from unittest import mock

from chutku import dashboard


class AppWindowTests(unittest.TestCase):
    URL = "http://127.0.0.1:8765/#token=abc"

    def test_installed_opens_an_app_mode_window_with_its_own_profile(self):
        with mock.patch("chutku.core.paths.is_checkout", return_value=False), \
                mock.patch.object(dashboard.Path, "is_file", return_value=True), \
                mock.patch("subprocess.Popen") as popen, mock.patch("webbrowser.open") as browser:
            dashboard.open_app_window(self.URL)
        args = popen.call_args[0][0]
        self.assertTrue(args[0].endswith("msedge.exe"))
        self.assertIn(f"--app={self.URL}", args)
        self.assertTrue(any(a.startswith("--user-data-dir=") and a.endswith("app-window") for a in args))
        browser.assert_not_called()

    def test_a_checkout_or_no_edge_uses_the_default_browser(self):
        for checkout, edge in ((True, True), (False, False)):
            with mock.patch("chutku.core.paths.is_checkout", return_value=checkout), \
                    mock.patch.object(dashboard.Path, "is_file", return_value=edge), \
                    mock.patch("subprocess.Popen") as popen, mock.patch("webbrowser.open") as browser:
                dashboard.open_app_window(self.URL)
            browser.assert_called_once_with(self.URL)
            popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()

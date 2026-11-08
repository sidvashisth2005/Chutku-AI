"""2026-11-08: the required first-run setup (a working AI key before Chutku opens), in-app updates, the Voice lock
tab's status and the new brand icon. Nothing here reaches the network: providers and GitHub are faked."""
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import urllib.error
from unittest.mock import patch

from chutku import setup_wizard, updates

RELEASE = {"tag_name": "v9.9.0", "body": "## What's new\n- Faster", "assets": [
    {"name": "Chutku-Setup-for-Windows.exe", "size": 4, "digest": "sha256:" + "a" * 64,
     "browser_download_url": updates.DOWNLOADS + "v9.9.0/Chutku-Setup-for-Windows.exe"}]}


class KeyCheck(unittest.TestCase):
    def test_a_refused_key_is_never_stored(self):
        def refuse(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO())
        with self.assertRaises(ValueError) as refused:
            setup_wizard.check_brain_key("groq", "gsk_" + "x" * 40, opener=refuse)
        self.assertIn("did not accept", str(refused.exception))
        self.assertNotIn("gsk_", str(refused.exception))                          # the key never in the message
        with TemporaryDirectory() as base, patch("chutku.providers.store_key") as store:
            with self.assertRaises(ValueError):
                setup_wizard.store_brain_key(base, "groq", "gsk_" + "x" * 40,
                                             check=lambda p, k: setup_wizard.check_brain_key(p, k, opener=refuse))
            store.assert_not_called()

    def test_offline_is_explained_and_rate_limited_counts_as_working(self):
        def offline(request, timeout):
            raise urllib.error.URLError("no route")
        with self.assertRaises(ValueError) as error:
            setup_wizard.check_brain_key("gemini", "AIza" + "x" * 35, opener=offline)
        self.assertIn("internet", str(error.exception))

        def busy(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO())
        self.assertTrue(setup_wizard.check_brain_key("groq", "gsk_" + "y" * 40, opener=busy))

    def test_the_key_goes_in_a_header_to_the_right_provider(self):
        seen = []

        class Ok(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        setup_wizard.check_brain_key("groq", "gsk_K", opener=lambda r, timeout: seen.append(r) or Ok(b"{}"))
        setup_wizard.check_brain_key("gemini", "AIzaK", opener=lambda r, timeout: seen.append(r) or Ok(b"{}"))
        self.assertEqual(seen[0].get_header("Authorization"), "Bearer gsk_K")
        self.assertTrue(seen[0].full_url.startswith("https://api.groq.com/"))
        self.assertEqual(seen[1].get_header("X-goog-api-key"), "AIzaK")
        self.assertNotIn("AIzaK", seen[1].full_url)                               # never in the URL


class FinishNeedsAKey(unittest.TestCase):
    def test_finish_is_refused_without_a_key_and_allowed_with_one(self):
        from tests.test_setup_page_w5 import Server
        with TemporaryDirectory() as base:
            web = Server(base)
            try:
                with patch.object(setup_wizard, "has_brain_key", lambda b: False):
                    status, view = web.call("POST", "/api/setup", {"action": "finish"})
                self.assertEqual(status, 400)
                self.assertIn("AI key", view["error"])
                self.assertFalse(setup_wizard.state(base)["done"])
                with patch.object(setup_wizard, "has_brain_key", lambda b: True):
                    self.assertEqual(web.call("POST", "/api/setup", {"action": "finish"})[0], 200)
                self.assertTrue(setup_wizard.state(base)["done"])
                # 2026-11-08: the Voice lock tab opens with "status" (it used to answer "Unknown action.")
                status, voice = web.call("POST", "/api/voice/enroll", {"action": "status"})
                self.assertEqual(status, 200, voice)
                self.assertIn("voice_lock", voice)
            finally:
                web.close()


class Updates(unittest.TestCase):
    def setUp(self):
        updates.reset_for_tests()
        self.addCleanup(updates.reset_for_tests)

    def test_a_newer_release_is_offered_and_cached(self):
        calls = []
        fetch = lambda url: calls.append(url) or RELEASE
        with patch.object(updates, "current_version", lambda: "1.1.0"):
            first = updates.check(fetch=fetch, clock=lambda: 1e6)
            again = updates.check(fetch=fetch, clock=lambda: 1e6 + 60)
        self.assertEqual((first["available"], first["latest"], first["current"]), (True, "9.9.0", "1.1.0"))
        self.assertIn("Faster", first["notes"])
        self.assertEqual(len(calls), 1)                                           # cached for 6 hours
        self.assertEqual(again["latest"], "9.9.0")

    def test_no_popup_when_current_offline_or_the_asset_is_foreign(self):
        with patch.object(updates, "current_version", lambda: "9.9.0"):
            self.assertFalse(updates.check(fetch=lambda u: RELEASE, force=True)["available"])
        with patch.object(updates, "current_version", lambda: "1.0.0"):
            self.assertFalse(updates.check(fetch=lambda u: (_ for _ in ()).throw(OSError("offline")), force=True)["available"])
            evil = json.loads(json.dumps(RELEASE))
            evil["assets"][0]["browser_download_url"] = "https://evil.example/Chutku-Setup-for-Windows.exe"
            self.assertFalse(updates.check(fetch=lambda u: evil, force=True)["available"])
        self.assertTrue(updates.newer("1.10.0", "1.9.9"))
        self.assertFalse(updates.newer("1.1.0", "1.1.0"))

    def test_install_downloads_checks_and_launches_and_refuses_a_bad_file(self):
        import hashlib
        launched = []
        with patch.object(updates, "current_version", lambda: "1.0.0"), patch.object(updates, "is_checkout", lambda: False):
            updates.check(fetch=lambda u: RELEASE, force=True)
            with TemporaryDirectory() as folder:
                def bad(url, target, size, sha, progress):
                    Path(target).write_bytes(b"evil")
                    if hashlib.sha256(b"evil").hexdigest() != sha:
                        Path(target).unlink()
                        raise OSError("The downloaded update did not match its checksum and was deleted.")
                updates.install(download=bad, launch=launched.append, folder=folder)
                for _ in range(100):
                    if updates.check()["job"]["state"] not in ("downloading", "installing"):
                        break
                    __import__("time").sleep(0.02)
                job = updates.check()["job"]
                self.assertEqual(job["state"], "failed")
                self.assertIn("checksum", job["error"])
                self.assertEqual(launched, [])                                    # a bad file is never run
                self.assertFalse((Path(folder) / updates.SETUP_NAME).exists())
                updates._STATE["job"] = {"state": "idle"}
                updates.install(download=lambda *a: None, launch=launched.append, folder=folder)
                for _ in range(100):
                    if launched:
                        break
                    __import__("time").sleep(0.02)
                self.assertEqual(launched, [Path(folder) / updates.SETUP_NAME])

    def test_the_real_download_deletes_a_file_with_the_wrong_checksum(self):
        import hashlib

        class Body(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with TemporaryDirectory() as folder, patch("urllib.request.urlopen", lambda r, timeout: Body(b"evil")):
            target = Path(folder) / "setup.exe"
            with self.assertRaises(OSError):
                updates._download("https://x", target, 4, "a" * 64, lambda done: None)
            self.assertFalse(target.exists())
            with self.assertRaises(OSError):                                      # a short file, even without a digest
                updates._download("https://x", target, 99, None, lambda done: None)
            updates._download("https://x", target, 4, hashlib.sha256(b"evil").hexdigest(), lambda done: None)
            self.assertEqual(target.read_bytes(), b"evil")

    def test_a_developer_copy_never_installs(self):
        with patch.object(updates, "is_checkout", lambda: True):
            with self.assertRaises(ValueError):
                updates.install(download=lambda *a: None, launch=lambda s: None)


class BrandIcon(unittest.TestCase):
    def test_the_png_and_ico_are_drawn(self):
        from chutku import icon
        png = icon.png_bytes(64)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        rows = icon._rgba(64)
        corner, centre_left = rows[0][:4], rows[32][4 * 18:4 * 18 + 4]           # transparent corner, white "c"
        self.assertEqual(corner[3], 0)
        self.assertEqual(tuple(centre_left[:3]), (255, 255, 255))
        self.assertEqual(tuple(rows[32][4 * 4:4 * 4 + 3]), icon.BRAND)              # brand orange inside the square
        self.assertTrue(icon.icon_bytes().startswith(b"\x00\x00\x01\x00"))


if __name__ == "__main__":
    unittest.main()

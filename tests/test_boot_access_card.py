"""2026-11-08: the Phone tab's Telegram card and "Reach this laptop after a restart", for every install.
Nothing here talks to Telegram or asks Windows for admin rights: both are replaced by fakes."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from chutku.gateway import telegram
from chutku.remote import boot

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + "B" * 35


class TelegramEndpoint(unittest.TestCase):
    def setUp(self):
        from tests.test_setup_page_w5 import Server
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.web = Server(self.temp.name)
        self.addCleanup(self.web.close)

    def test_the_token_is_checked_stored_and_never_echoed(self):
        fake = lambda method, params, timeout: {"username": "asha_chutku_bot"}
        with patch.object(telegram, "_real_transport", lambda value: fake), \
                patch.object(telegram, "store_token") as store, patch.object(telegram, "start") as start:
            status, view = self.web.call("POST", "/api/telegram", {"action": "token", "token": "nope"})
            self.assertEqual(status, 400)                                       # a bad token: refused, nothing stored
            store.assert_not_called()
            status, view = self.web.call("POST", "/api/telegram", {"action": "token", "token": TOKEN})
        self.assertEqual((status, view["bot"], view["token_stored"]), (200, "asha_chutku_bot", True))
        store.assert_called_once_with(TOKEN)
        start.assert_called_once()                                              # the bot starts without a restart
        self.assertNotIn(TOKEN, str(view))
        self.assertEqual(self.web.call("POST", "/api/telegram", {"action": "token"})[0], 400)   # extra/missing fields

    def test_pairing_gives_a_tap_link_with_the_code(self):
        telegram.save(self.temp.name, {"bot": "asha_chutku_bot"})
        status, view = self.web.call("POST", "/api/telegram", {"action": "pair"})
        self.assertEqual(status, 200)
        self.assertEqual(view["link"], f"https://t.me/asha_chutku_bot?start={view['code']}")
        self.assertTrue(view["qr_svg"] is None or "<svg" in view["qr_svg"])

    def test_the_endpoint_refuses_a_bad_session_token(self):
        self.assertEqual(self.web.call("POST", "/api/telegram", {"action": "token", "token": TOKEN}, token="x")[0], 403)


class BootAccess(unittest.TestCase):
    def test_on_needs_the_log_and_the_helper(self):
        with TemporaryDirectory() as temp:
            log = Path(temp) / "notify.log"
            self.assertFalse(boot.status(log=log, answers=lambda: True)["on"])     # never set up
            log.write_text("﻿2026-11-08 10:21:41 sending\n2026-11-08 10:21:42 sent on try 1\n", encoding="utf-8")
            on = boot.status(log=log, answers=lambda: True)
            self.assertEqual((on["on"], on["last"]), (True, "2026-11-08 10:21:42 sent on try 1"))
            self.assertFalse(boot.status(log=log, answers=lambda: False)["on"])    # the helper is not running

    def test_turning_on_waits_for_telegram_and_never_starts_windows_prompt(self):
        launched = []
        with TemporaryDirectory() as base, patch.object(telegram, "token", lambda: None):
            result = boot.run(base, True, launch=lambda *a, **k: launched.append(a))
        self.assertFalse(result["started"])
        self.assertIn("Telegram", result["message"])
        self.assertEqual(launched, [])
        with TemporaryDirectory() as base, patch.object(telegram, "token", lambda: TOKEN):
            telegram.save(base, {"chat_id": 5})
            result = boot.run(base, True, launch=lambda *a, **k: launched.append(a))
        self.assertIn("Tailscale", result["message"])                          # not signed in to Tailscale yet
        self.assertEqual(launched, [])

    def test_the_elevated_script_is_started_when_ready_and_off_needs_nothing(self):
        launched = []
        with TemporaryDirectory() as base, patch.object(telegram, "token", lambda: TOKEN):
            from chutku.remote.auth import RemoteStore
            telegram.save(base, {"chat_id": 5})
            RemoteStore(base).configure(host="laptop.tail1.ts.net", login="me@example.com", enabled=True)
            self.assertTrue(boot.run(base, True, launch=lambda args, **k: launched.append(args))["started"])
        with TemporaryDirectory() as base, patch.object(telegram, "token", lambda: None):
            self.assertTrue(boot.run(base, False, launch=lambda args, **k: launched.append(args),
                                     installed=base)["started"])
            # 2026-11-08 review: nothing installed -> no admin prompt at all
            gone = boot.run(base, False, launch=lambda args, **k: launched.append(args), installed=Path(base) / "x")
            self.assertEqual(gone, {"started": False, "message": "It is already off."})
        self.assertEqual(len(launched), 2)
        self.assertIn("-Verb RunAs", launched[0][-1])
        self.assertIn("setup_boot_access.ps1", launched[0][-1])
        self.assertIn("remove_boot_access.ps1", launched[1][-1])

    def test_curly_quotes_in_the_install_path_stay_inside_the_powershell_string(self):
        launched = []
        with TemporaryDirectory() as base, patch.object(boot, "script", lambda name: Path("C:/Users/O\u2019Brien's/x.ps1")):
            boot.run(base, False, launch=lambda args, **k: launched.append(args), installed=base)
        inner = launched[0][-1].split("-ArgumentList '", 1)[1][:-1]
        for quote in "'\u2018\u2019\u201a\u201b":   # every single quote PowerShell knows is doubled, so none ends it
            self.assertNotRegex(inner.replace(quote * 2, ""), quote)

    def test_the_system_helpers_folder_is_never_reused_or_user_owned(self):
        # 2026-11-08 review: a normal user could pre-create C:\\ProgramData\\ChutkuBoot, stay its owner and swap the
        # SYSTEM helper. The script must refuse links, replace an existing folder and give it to Administrators.
        setup = (ROOT / "scripts" / "setup_boot_access.ps1").read_text(encoding="utf-8")
        remove = (ROOT / "scripts" / "remove_boot_access.ps1").read_text(encoding="utf-8")
        before = setup.index("New-Item -ItemType Directory -Force $boot")
        self.assertIn("ReparsePoint", setup[:before])
        self.assertIn('rmdir /s /q', setup[:before])
        self.assertEqual(setup.count('SetOwner([Security.Principal.SecurityIdentifier]"S-1-5-32-544")'), 2)
        self.assertNotIn("Remove-Item -Recurse -Force $boot", remove)   # PowerShell 5.1 can follow junctions

    def test_the_scripts_ship_and_leave_other_software_alone(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("build_release", ROOT / "scripts" / "build_release.py")
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        self.assertEqual({Path(p).name for p in build.BOOT_ACCESS},
                         {"setup_boot_access.ps1", "remove_boot_access.ps1", "ChutkuUnlock.cs", "notify.ps1"})
        for source in build.BOOT_ACCESS:
            self.assertTrue((ROOT / source).is_file(), source)
        setup = (ROOT / "scripts" / "setup_boot_access.ps1").read_text(encoding="utf-8")
        self.assertNotIn("RustDesk", setup)                  # it would uninstall another user's software
        self.assertIn('python\\python.exe', setup)            # an installed app's Python
        self.assertIn("param([switch]$Quiet)", setup)


if __name__ == "__main__":
    unittest.main()

"""Lock-screen helper (scripts/boot_access/ChutkuUnlock.cs, owner 2026-11-07): compiled and run as a normal user.

The positive path (SYSTEM on the Winlogon desktop) needs the owner's admin setup and a locked laptop; this proves the
refusals: wrong address, wrong Tailscale login, missing or wrong key, and no picture or input while unlocked.
"""
import ctypes
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "boot_access" / "ChutkuUnlock.cs"
CSC = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
HOST, LOGIN, KEY = "laptop.example.ts.net", "owner@example.com", "ab" * 32


def compile_to(folder):
    exe = Path(folder) / "ChutkuUnlock.exe"
    done = subprocess.run([str(CSC), "-nologo", "-optimize", f"-out:{exe}", "-r:System.Drawing.dll",
                           "-r:System.Web.Extensions.dll", str(SOURCE)], capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(done.stdout + done.stderr)
    return exe


def cursor():
    point = (ctypes.c_long * 2)()
    ctypes.windll.user32.GetCursorPos(point)
    return tuple(point)


@unittest.skipUnless(sys.platform == "win32" and CSC.is_file(), "Windows with .NET Framework 4 only")
class LockScreenHelper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = TemporaryDirectory()
        cls.exe = compile_to(cls.folder.name)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        Path(cls.folder.name, "config.json").write_text(json.dumps(
            {"host": HOST, "login": LOGIN, "unlock_port": cls.port, "unlock_https_port": 8443}), encoding="utf-8")
        Path(cls.folder.name, "key.txt").write_text(KEY, encoding="utf-8")
        cls.proc = subprocess.Popen([str(cls.exe), "screen"], cwd=cls.folder.name)
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.kill()
        cls.proc.wait()
        cls.folder.cleanup()

    def call(self, method, path, *, host=f"{HOST}:8443", login=LOGIN, key=KEY, body=None):
        headers = {"Host": host, "Tailscale-User-Login": login}
        if key:
            headers["X-Chutku-Key"] = key
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body=body, headers=headers)
        reply = conn.getresponse()
        return reply.status, reply.read()

    def test_gate_is_closed_while_signed_in(self):
        gate = json.loads(subprocess.run([str(self.exe), "gate"], capture_output=True, text=True, check=True).stdout)
        self.assertNotEqual(gate["desktop"].casefold(), "winlogon")   # "Default" here; "" on a headless CI runner
        self.assertFalse(gate["open"])

    def test_only_this_laptop_name_and_the_owner(self):
        self.assertEqual(self.call("GET", "/", host=HOST)[0], 403)                 # no :8443
        self.assertEqual(self.call("GET", "/", host="evil.example:8443")[0], 403)
        self.assertEqual(self.call("GET", "/", login="someone@else.com")[0], 403)
        self.assertEqual(self.call("GET", "/", login="")[0], 403)                  # Funnel: no Tailscale login
        status, page = self.call("GET", "/", key=None)
        self.assertEqual(status, 200)
        self.assertIn(b"X-Chutku-Key", page)

    def test_the_boot_key_is_required(self):
        self.assertEqual(self.call("GET", "/api/frame", key=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/frame", key="cd" * 32)[0], 401)
        self.assertEqual(self.call("POST", "/api/key?name=enter", key="ab")[0], 401)

    def test_no_picture_and_no_input_while_unlocked(self):
        start = time.perf_counter()
        status, text = self.call("GET", "/api/frame")
        self.assertEqual((status, text), (409, b"unlocked"))
        moved_away = cursor() != (0, 0)
        self.assertEqual(self.call("POST", "/api/click?x=0&y=0")[0], 409)
        self.assertEqual(self.call("POST", "/api/text", body="secret".encode())[0], 409)
        self.assertEqual(self.call("POST", "/api/key?name=enter")[0], 409)
        if moved_away:
            self.assertNotEqual(cursor(), (0, 0))   # the pointer was not sent to the corner
        self.assertLess(time.perf_counter() - start, 5)
        log = Path(self.folder.name, "unlock.log").read_text(encoding="utf-8")
        self.assertNotIn("secret", log)


if __name__ == "__main__":
    unittest.main()

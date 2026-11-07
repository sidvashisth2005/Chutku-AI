"""W8: the built zip is scanned for personal data and secrets before it is kept; .pyc carry no build path."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_release as build  # noqa: E402

GROQ = "gsk_" + "A1b2C3d4" * 6     # built here, so this file holds no key-shaped literal


class ScanTests(unittest.TestCase):
    def scan(self, files, user="asha"):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "p.zip"
            with zipfile.ZipFile(path, "w") as bundle:
                for name, data in files.items():
                    bundle.writestr(name, data)
            return build.scan_zip(path, user=user)

    @staticmethod
    def pyc(source_path, constant):
        import marshal
        return b"\0" * 16 + marshal.dumps(compile(f"X = {constant!r}", source_path, "exec"))

    def test_a_clean_package_passes(self):
        self.assertEqual(self.scan({
            "LICENSE": "Copyright (c) 2026 Siddhant Vashisth",                     # the copyright line is allowed
            "chutku/app.pyc": b"chutku/app.py",
            "python/Lib/site-packages/x/data/table.csv": "1,2",                     # a wheel's own data/ folder
            "python/Lib/site-packages/x/_x.pyd": "C:\\Users\\asha\\build\\x.c",       # a wheel's own CI path
            "bin/agent-desktop-win32-x64.exe": "C:\\Users\\asha\\work\\",             # a pinned helper's CI path
            "python/Lib/site-packages/n/__pycache__/__config__.cpython-313.pyc": self.pyc(
                "python/Lib/site-packages/n/__config__.py", "C:\\Users\\asha\\numpy-build\\"),   # data, not path
            "python/Lib/site-packages/c/ssh.pyc": b"-----BEGIN OPENSSH PRIVATE KEY-----\"",   # the marker alone
            "docs/USER_GUIDE.md": "C:\\Users\\ashaXYZ is not this user"}), [])

    def test_personal_files_keys_names_and_user_paths_are_refused(self):
        problems = self.scan({
            "data/mind.json": "{}", ".env": "X=1", "chutku/data/conversations.jsonl": "{}",
            "chutku/web/app.js": f"const k = '{GROQ}';",
            "NOTICE": "made by Siddhant",
            "chutku/x.pyc": "D:\\Users\\asha\\Chutku\\stage\\chutku\\x.py",
            "python/Lib/site-packages/y/__pycache__/y.pyc": self.pyc(
                "C:\\Users\\asha\\AppData\\Local\\Temp\\pip-target\\y.py", "x"),
            "Chutku.exe": "C:\\Users\\asha\\".encode("utf-16-le"),
            "keys/id": "-----BEGIN RSA PRIVATE KEY-----\n" + "A" * 64})
        joined = "\n".join(problems)
        for needle in ("data/mind.json: personal", ".env: personal", "conversations.jsonl: personal",
                       "app.js: looks like a key", "NOTICE: the owner's name", "chutku/x.pyc: the builder's",
                       "y.pyc: the builder's", "Chutku.exe: the builder's", "keys/id: looks like a key"):
            self.assertIn(needle, joined)
        self.assertNotIn(GROQ, joined)                 # the report never repeats the secret

    def test_the_build_wires_the_scan_and_path_free_compiles(self):
        # build() itself needs Windows (csc) and the network; the Linux real-build run is in IMPLEMENTATION_STATUS.
        source = Path(build.__file__).read_text(encoding="utf-8")
        self.assertIn("target.unlink()", source.split("problems = scan_zip(target)")[1][:200])
        for call in ("--no-compile", '"-s", str(stage)'):
            self.assertIn(call, source)                # no pip temp path or stage path inside a .pyc


if __name__ == "__main__":
    unittest.main()

"""W3: the app package build (scripts/build_release.py), the launcher source and package-aware lookups."""
import hashlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_release as build  # noqa: E402


def fake_embed(path):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("python.exe", b"MZ")
        bundle.writestr("pythonw.exe", b"MZ")
        bundle.writestr("python313.zip", b"PK")
        bundle.writestr("python313._pth", "python313.zip\n.\n#import site\n")
    return path


class LockAndPythonTests(unittest.TestCase):
    def test_test_only_pins_are_left_out_and_hashes_kept(self):
        with TemporaryDirectory() as temp:
            text = build.lock_without_test_pins(temp).read_text()
        self.assertNotIn("hypothesis==", text)
        self.assertNotIn("sortedcontainers==", text)
        self.assertRegex(text, r"numpy==2\.5\.3 +--hash=sha256:")
        self.assertTrue(all("--hash=sha256:" in line for line in text.splitlines()))

    def test_the_embedded_python_finds_chutku_and_site_packages(self):
        with TemporaryDirectory() as temp:
            archive = fake_embed(Path(temp) / "embed.zip")
            stage = Path(temp) / "stage"
            build.install_python(stage, archive, {"version": "3.13.9"})
            self.assertEqual((stage / "python" / "python313._pth").read_text().splitlines(),
                             ["python313.zip", ".", "Lib\\site-packages", "..", "import site"])

    def test_a_tampered_or_unpinned_python_zip_is_refused(self):
        with TemporaryDirectory() as temp:
            archive = fake_embed(Path(temp) / "embed.zip")
            good = hashlib.sha256(archive.read_bytes()).hexdigest()
            pin = {"python": {"version": "3.13.9", "source": "https://x/python-3.13.9-embed-amd64.zip",
                              "sha256": good}}
            with patch.object(build, "manifest", return_value=pin):
                self.assertEqual(build.python_zip(temp, archive)[0], archive)
            with patch.object(build, "manifest", return_value={"python": {**pin["python"], "sha256": "0" * 64}}):
                with self.assertRaises(build.BuildError):
                    build.python_zip(temp, archive)
            with patch.object(build, "manifest", return_value={}):
                with self.assertRaises(build.BuildError):
                    build.python_zip(temp, archive)

    def test_newest_embed_skips_versions_without_an_embeddable_zip(self):
        listing = b'<a href="3.13.8/">3.13.8/</a><a href="3.13.10/">3.13.10/</a><a href="3.12.9/">x</a>'

        def opener(request, timeout=30):
            url = request if isinstance(request, str) else request.full_url
            if url == build.FTP:
                return io.BytesIO(listing)
            if "3.13.10" in url:
                raise OSError("404")
            return io.BytesIO(b"")
        self.assertEqual(build.newest_embed(opener)[0], "3.13.8")


class StageTests(unittest.TestCase):
    def test_chutku_is_compiled_and_no_source_is_shipped(self):
        with TemporaryDirectory() as temp:
            stage = Path(temp)
            build.compile_chutku(stage)
            self.assertEqual(list((stage / "chutku").rglob("*.py")), [])
            self.assertTrue((stage / "chutku" / "dashboard.pyc").is_file())
            self.assertTrue((stage / "chutku" / "web" / "index.html").is_file())     # bundled assets kept
            self.assertTrue((stage / "chutku" / "apps" / "atlas" / "spotify.json").is_file())
            self.assertFalse(any("__pycache__" in p.parts for p in (stage / "chutku").rglob("*")))

    def test_personal_or_source_files_are_refused(self):
        for bad in ("data/mind.json", ".env", "chutku/x.py", "tests/test_a.py", "sandbox/a.txt"):
            with TemporaryDirectory() as temp, self.subTest(bad=bad):
                path = Path(temp) / bad
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x")
                with self.assertRaises(build.BuildError):
                    build.check_stage(Path(temp))
        with TemporaryDirectory() as temp:   # an ASIO PortAudio build is refused even inside python/
            asio = Path(temp) / "python" / "Lib" / "site-packages" / "_sounddevice_data" / "libportaudio64bit-asio.dll"
            asio.parent.mkdir(parents=True)
            asio.write_bytes(b"MZ")
            with self.assertRaises(build.BuildError):
                build.check_stage(Path(temp))
        self.assertTrue(build.EXCLUDED_FILES.search("_sounddevice_data/portaudio-binaries/libportaudioarm64-asio.dll"))
        self.assertFalse(build.EXCLUDED_FILES.search("_sounddevice_data/portaudio-binaries/libportaudio64bit.dll"))
        with TemporaryDirectory() as temp:   # the embedded python's own .py files are fine
            (Path(temp) / "python" / "Lib" / "site-packages").mkdir(parents=True)
            (Path(temp) / "python" / "Lib" / "site-packages" / "x.py").write_text("x")
            build.check_stage(Path(temp))

    def test_a_native_helper_that_does_not_match_its_sha256_is_refused(self):
        with TemporaryDirectory() as temp:
            tools = Path(temp) / "node_modules"
            for name, relative in build.NATIVE.items():
                exe = tools / relative
                exe.parent.mkdir(parents=True, exist_ok=True)
                exe.write_bytes(b"MZ" + name.encode())
            desktop = tools / build.NATIVE["agent-desktop"]
            desktop.with_name(desktop.name + ".sha256").write_text(hashlib.sha256(b"MZagent-desktop").hexdigest())
            stage = Path(temp) / "stage"
            build.copy_bundles(stage, tools)
            self.assertTrue((stage / "bin" / "agent-desktop-win32-x64.exe").is_file())
            self.assertTrue((stage / "models" / "manifest.json").is_file())
            self.assertTrue((stage / "docs" / "apps" / "spotify.md").is_file())
            desktop.with_name(desktop.name + ".sha256").write_text("0" * 64)
            with self.assertRaises(build.BuildError):
                build.copy_bundles(Path(temp) / "stage2", tools)

    def test_the_zip_holds_the_stage(self):
        with TemporaryDirectory() as temp:
            stage = Path(temp) / "stage"
            (stage / "chutku").mkdir(parents=True)
            (stage / "chutku" / "a.pyc").write_bytes(b"x")
            target = build.make_zip(stage, Path(temp) / "dist", "1.0.0")
            self.assertEqual(target.name, "Chutku-1.0.0-win64.zip")
            self.assertEqual(zipfile.ZipFile(target).namelist(), ["chutku/a.pyc"])

    def test_notice_names_the_special_licences(self):
        with TemporaryDirectory() as temp:
            build.notice(Path(temp))
            text = (Path(temp) / "NOTICE").read_text()
        self.assertIn("CC BY-NC-SA 4.0", text)
        self.assertIn("GPL", text)
        self.assertIn("ASIO variant is not included", text)


class LauncherAndLookupTests(unittest.TestCase):
    def test_the_launcher_source(self):
        source = (ROOT / "installer" / "launcher.cs").read_text()
        for needed in ('"Local\\\\Chutku.Launcher"', 'EnvironmentVariables["CHUTKU_HOME"]', "pythonw.exe",
                       "-m chutku.guard", "-m chutku.cli open", "PYTHONDONTWRITEBYTECODE", "CreateNoWindow = true",
                       "--background", "AssemblyVersion(\"0.0.0.0\")"):
            self.assertIn(needed, source)

    def test_autostart_points_at_the_launcher_in_a_package(self):
        from chutku import autostart
        from chutku.core import paths
        with TemporaryDirectory() as temp:
            (Path(temp) / "Chutku.exe").write_bytes(b"MZ")
            with patch.object(paths, "CODE_ROOT", Path(temp)), patch.object(paths, "is_checkout", return_value=False):
                program, arguments, folder = autostart.launch_command()
            self.assertEqual((program, arguments, folder), (Path(temp) / "Chutku.exe", "--background", Path(temp)))
        with patch.object(paths, "is_checkout", return_value=True):
            program, arguments, _ = autostart.launch_command()
        self.assertEqual((program.name, arguments), ("pythonw.exe", "-m chutku.guard"))

    def test_the_native_helpers_are_found_in_the_package_bin(self):
        from chutku.tools import desktop, signed_in_browser
        with TemporaryDirectory() as temp:
            (Path(temp) / "bin").mkdir()
            (Path(temp) / "bin" / "agent-desktop-win32-x64.exe").write_bytes(b"MZ")
            (Path(temp) / "bin" / "agent-browser-win32-x64.exe").write_bytes(b"MZ")
            env = {"CHUTKU_AGENT_DESKTOP": "", "CHUTKU_AGENT_BROWSER": "", "PROCESSOR_ARCHITECTURE": "AMD64"}
            with patch.dict("os.environ", env), patch.object(desktop, "ROOT", Path(temp)), \
                    patch.object(signed_in_browser, "ROOT", Path(temp)), patch("shutil.which", return_value=None):
                self.assertTrue(desktop.binary().endswith("agent-desktop-win32-x64.exe"))
                self.assertTrue(signed_in_browser.binary().endswith("agent-browser-win32-x64.exe"))


if __name__ == "__main__":
    unittest.main()

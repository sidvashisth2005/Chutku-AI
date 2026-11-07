"""W2: Chutku's state lives in home() (CHUTKU_HOME, else the repo in a git checkout, else %LOCALAPPDATA%/Chutku).
With CHUTKU_HOME set, nothing is written under the code folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest
from unittest.mock import patch

from chutku.core import paths

CODE = paths.CODE_ROOT
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".hypothesis"}


def code_files():
    """Every file under the code folder (paths only), without caches and git internals."""
    found = set()
    for root, dirs, files in os.walk(CODE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        found.update(os.path.relpath(os.path.join(root, f), CODE) for f in files if not f.endswith(".pyc"))
    return found


class HomeTests(unittest.TestCase):
    def test_chutku_home_wins(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"CHUTKU_HOME": temp}):
            self.assertEqual(paths.home(), Path(temp).resolve())
            self.assertEqual(paths.data_dir(), Path(temp).resolve() / "data")
            self.assertEqual(paths.models_dir(), Path(temp).resolve() / "models")

    def test_a_git_checkout_keeps_data_in_the_repo(self):
        env = {k: v for k, v in os.environ.items() if k != "CHUTKU_HOME"}
        with patch.dict(os.environ, env, clear=True), patch.object(paths, "is_checkout", return_value=True):
            self.assertEqual(paths.home(), CODE)

    def test_an_installed_package_uses_localappdata(self):
        env = {k: v for k, v in os.environ.items() if k != "CHUTKU_HOME"} | {"LOCALAPPDATA": "/users/x/AppData/Local"}
        with patch.dict(os.environ, env, clear=True), patch.object(paths, "is_checkout", return_value=False):
            self.assertEqual(paths.home(), Path("/users/x/AppData/Local") / "Chutku")

    def test_resource_falls_back_to_the_code_folder_only_for_the_real_home(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"CHUTKU_HOME": temp}):
            self.assertEqual(paths.resource(temp, "models/manifest.json"), CODE / "models/manifest.json")
            (Path(temp) / "models").mkdir()
            (Path(temp) / "models/manifest.json").write_text("{}")
            self.assertEqual(paths.resource(temp, "models/manifest.json"), Path(temp) / "models/manifest.json")
        with TemporaryDirectory() as other:   # a test's own base never sees the code folder's files
            self.assertEqual(paths.resource(other, "models/manifest.json"), Path(other) / "models/manifest.json")

    def test_model_file_stays_inside_the_models_folders(self):
        with TemporaryDirectory() as temp:
            (Path(temp) / "models" / "embed").mkdir(parents=True)
            self.assertIsNotNone(paths.model_file(temp, "models/x.gguf"))
            self.assertIsNone(paths.model_file(temp, "models/embed/m.onnx"))            # not directly inside
            self.assertIsNotNone(paths.model_file(temp, "models/embed/m.onnx", nested=True))
            for bad in ("../x.gguf", "models/../../etc/passwd", "/etc/passwd", "", None, "models"):
                self.assertIsNone(paths.model_file(temp, bad, nested=True), bad)

    def test_home_is_protected_but_its_sandbox_is_not(self):
        if os.name != "nt":
            self.skipTest("protection_reason resolves Windows drive paths")   # needs the Windows check
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"CHUTKU_HOME": temp}):
            self.assertIsNotNone(paths.protection_reason(Path(temp) / "data" / "mind.json"))
            self.assertIsNone(paths.protection_reason(Path(temp) / "sandbox" / "a.txt"))

    def test_the_home_is_in_the_protected_zones(self):
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"CHUTKU_HOME": temp}):
            self.assertIn(os.path.normcase(os.path.normpath(str(Path(temp).resolve()))), paths.protected_zones())

    def test_new_install_defaults_never_touch_a_checkout(self):
        from chutku.core import preferences
        with TemporaryDirectory() as temp:
            with patch.object(paths, "is_checkout", return_value=True):
                values = preferences.Preferences(Path(temp)).load()
                self.assertEqual((values["handsfree_mode"], values["browser"]), ("owner", "brave"))
            with patch.object(paths, "is_checkout", return_value=False):
                values = preferences.Preferences(Path(temp)).load()
                self.assertEqual((values["handsfree_mode"], values["browser"]), ("auto_safe", "default"))
                (Path(temp) / "data").mkdir()
                (Path(temp) / "data" / "preferences.json").write_text(json.dumps({"handsfree_mode": "owner"}))
                self.assertEqual(preferences.Preferences(Path(temp)).load()["handsfree_mode"], "owner")   # kept

    def test_the_default_browser_and_its_history(self):
        from chutku import know_me
        self.assertEqual(know_me.default_browser(lambda: "ChromeHTML.ABC"), "chrome")
        self.assertEqual(know_me.default_browser(lambda: "MSEdgeHTM"), "edge")
        self.assertIsNone(know_me.default_browser(lambda: "SomethingElse"))
        self.assertEqual(know_me.history_db("chrome").parts[-5:], ("Google", "Chrome", "User Data", "Default",
                                                                   "History"))
        self.assertIsNone(know_me.history_db("firefox"))     # a different format: not read
        with patch.object(know_me, "default_browser", return_value="edge"):
            self.assertIn("Edge", str(know_me.history_db("default")))

    def test_an_installed_icon_goes_to_the_data_folder(self):
        from chutku import icon
        with TemporaryDirectory() as temp, patch.dict(os.environ, {"CHUTKU_HOME": temp}), \
                patch.object(icon, "ICON_PATH", Path(temp) / "missing" / "chutku.ico"), \
                patch.object(paths, "is_checkout", return_value=False):
            made = icon.ensure_icon()
            self.assertEqual(made, Path(temp).resolve() / "data" / "chutku.ico")
            self.assertTrue(made.is_file())


WRITERS = textwrap.dedent("""
    import json, os, sys
    from pathlib import Path
    from chutku.core.paths import home
    assert home() == Path(os.environ["CHUTKU_HOME"]).resolve(), home()
    from chutku.app import PROJECT_ROOT
    from chutku import recall, notes, routines, identity, learning, mind, suggest, know_me, drive_index, hud, icon
    from chutku.core.preferences import Preferences
    from chutku.core.log import get_logger
    from chutku.tools.registry import ToolRegistry
    from chutku.tools.builtin import register_builtin_tools
    import chutku.dashboard, chutku.cli, chutku.guard, chutku.presence, chutku.remind, chutku.tools.finance
    register_builtin_tools(ToolRegistry())
    Preferences(PROJECT_ROOT).update({"reply_style": "short"})
    recall.log_conversation("aaj kya date hai", "Friday.", base=PROJECT_ROOT)
    get_logger("w2").warning("a line in the log")
    routines._write({"padhai": ["volume 30"]})
    identity.save({"name": "Chutku"}) if hasattr(identity, "save") else None
    icon.ensure_icon()
    from chutku import board, blueprints
    board.add(PROJECT_ROOT, "DBMS notes")
    print(json.dumps(sorted(str(p.relative_to(home())) for p in home().rglob("*") if p.is_file())))
""")


class NothingUnderTheCodeFolderTests(unittest.TestCase):
    def run_child(self, script, temp):
        env = dict(os.environ, CHUTKU_HOME=temp, PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-c", script], cwd=str(CODE), env=env, capture_output=True, text=True,
                              timeout=300)

    def test_the_writers_go_to_chutku_home(self):
        before = code_files()
        with TemporaryDirectory() as temp:
            done = self.run_child(WRITERS, temp)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            written = json.loads(done.stdout.strip().splitlines()[-1])
        self.assertIn("data/preferences.json".replace("/", os.sep), written)
        self.assertTrue(any(p.startswith(os.path.join("data", "logs")) for p in written), written)
        self.assertEqual(code_files() - before, set())                  # nothing new under the code folder

    @unittest.skipUnless(sys.platform == "win32", "a real dashboard needs Windows (the windows-latest CI job)")
    def test_a_dashboard_start_stop_and_a_text_command_write_nothing_under_the_code_folder(self):
        script = textwrap.dedent("""
            import time
            from chutku.core.paths import home
            from chutku.dashboard import DashboardServer
            server = DashboardServer(base=home(), port=0)
            try:
                session = server.begin_session("what time is it", "owner", "text")
                deadline = time.time() + 60
                while session.status in ("planning", "running", "queued") and time.time() < deadline:
                    time.sleep(0.2)
                print("STATUS", session.status, session.reply[:120])
            finally:
                server.server_close()
        """)
        before = code_files()
        with TemporaryDirectory() as temp:
            done = self.run_child(script, temp)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            self.assertIn("STATUS done", done.stdout)
            self.assertTrue((Path(temp) / "data" / "chutku.db").is_file())
        self.assertEqual(code_files() - before, set())


if __name__ == "__main__":
    unittest.main()

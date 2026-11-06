import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chutku.app import PROJECT_ROOT, create_runtime
from chutku.coder import CoderError, GeminiCoder, parse_files
from chutku.core import progress
from chutku.tools import builder

BUGGY = '''PLAN: tiny calculator logic with tests
KIND: cli
RUN: main.py
=== FILE: calc.py ===
def add(a, b):
    return a - b
=== END FILE ===
=== FILE: main.py ===
from calc import add
print("2 + 3 =", add(2, 3))
=== END FILE ===
=== FILE: README.md ===
Run main.py.
=== END FILE ===
=== FILE: test_app.py ===
import unittest
from calc import add


class T(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
=== END FILE ===
'''
FIX = '''PLAN: add used subtraction
=== FILE: calc.py ===
def add(a, b):
    return a + b
=== END FILE ===
'''


class FakeCoder:
    name = "fake"
    model = "fake-1"

    def __init__(self, fixes):
        self.fixes = list(fixes)
        self.errors_seen = []

    def write(self, request):
        return parse_files(BUGGY)

    def fix(self, request, files, errors):
        self.errors_seen.append(errors)
        return parse_files(self.fixes.pop(0) if self.fixes else FIX.replace("a + b", "a * 0"), need_headers=False)


class ParseTests(unittest.TestCase):
    def test_parses_blocks_and_strips_code_fences(self):
        spec = parse_files("PLAN: p\nKIND: web\nRUN: index.html\n=== FILE: index.html ===\n```html\n<p>hi</p>\n```\n"
                           "=== END FILE ===\n")
        self.assertEqual(spec["files"], {"index.html": "<p>hi</p>\n"})
        self.assertEqual((spec["kind"], spec["run"]), ("web", "index.html"))

    def test_infers_entry_and_kind(self):
        spec = parse_files("=== FILE: app.py ===\nimport tkinter\n=== END FILE ===\n")
        self.assertEqual((spec["kind"], spec["run"]), ("gui", "app.py"))

    def test_refuses_unsafe_paths_types_and_empty_answers(self):
        for path in ("../x.py", "C:/Windows/x.py", "/etc/x.py", "a/b/c/d/e.py", "run.exe", "x.bat", "a:b.py"):
            with self.assertRaises(CoderError, msg=path):
                parse_files(f"=== FILE: {path} ===\nx\n=== END FILE ===\n")
        with self.assertRaises(CoderError):
            parse_files("Sure! Here is your app: print(1)")


class GeminiCoderTests(unittest.TestCase):
    def test_uses_code_purpose_and_parses(self):
        calls = []
        coder = GeminiCoder("k" * 30, generate_best=lambda key, purpose, *a, **k: (calls.append(purpose) or BUGGY,
                                                                                     "gemini-9-pro"))
        spec = coder.write("calculator")
        self.assertEqual(calls, ["code"])
        self.assertEqual(coder.model, "gemini-9-pro")
        self.assertIn("calc.py", spec["files"])


class GenerateBestTests(unittest.TestCase):
    def run_with(self, outcomes, models=("gemini-9-pro", "gemini-9-flash", "gemini-8-pro")):
        from chutku import gemini
        calls, sleeps = [], []

        def fake(key, model, *a, **k):
            calls.append(model)
            outcome = outcomes.pop(0)
            if isinstance(outcome, int):
                raise gemini.GeminiUnavailable(f"HTTP {outcome}", status=outcome)
            return outcome, model
        with patch.object(gemini, "ranked_models", return_value=list(models)), \
                patch.object(gemini, "generate", side_effect=fake):
            try:
                return gemini.generate_best("k" * 30, "code", "s", "u", sleep=sleeps.append, retries=2,
                                            backoff=(4, 12)), calls, sleeps
            except gemini.GeminiUnavailable as error:
                return error, calls, sleeps

    def test_overload_is_retried_with_backoff(self):
        result, calls, sleeps = self.run_with([503, 503, "ok"])
        self.assertEqual(result, ("ok", "gemini-9-pro"))
        self.assertEqual((calls, sleeps), (["gemini-9-pro"] * 3, [4, 12]))

    def test_retired_or_still_overloaded_model_moves_to_the_next(self):
        result, calls, _ = self.run_with([404, "ok"])
        self.assertEqual(result, ("ok", "gemini-9-flash"))
        result, calls, _ = self.run_with([503, 503, 503, "ok"])
        self.assertEqual(calls, ["gemini-9-pro"] * 3 + ["gemini-9-flash"])

    def test_quota_exhausted_model_is_skipped_without_retry(self):
        result, calls, sleeps = self.run_with([429, "ok"])
        self.assertEqual((result, calls, sleeps), (("ok", "gemini-9-flash"), ["gemini-9-pro", "gemini-9-flash"], []))

    def test_daily_quota_is_remembered_and_per_minute_limits_are_waited_out(self):
        import tempfile
        from chutku import gemini
        with tempfile.TemporaryDirectory() as temp, patch.object(gemini, "_QUOTA_FILE", Path(temp) / "q.json"):
            gemini._exhausted.clear()
            calls, sleeps = [], []

            def fake(key, model, *a, **k):
                calls.append(model)
                if model == "gemini-9-pro":
                    error = gemini.GeminiUnavailable("daily", status=429)
                    error.daily, error.retry_after = True, 30
                    raise error
                if len(calls) == 2:
                    error = gemini.GeminiUnavailable("per minute", status=429)
                    error.daily, error.retry_after = False, 7
                    raise error
                return "ok", model
            with patch.object(gemini, "ranked_models", return_value=["gemini-9-pro", "gemini-9-flash"]),                     patch.object(gemini, "generate", side_effect=fake):
                self.assertEqual(gemini.generate_best("k" * 30, "plan", "s", "u", sleep=sleeps.append),
                                 ("ok", "gemini-9-flash"))
                self.assertEqual((calls, sleeps), (["gemini-9-pro", "gemini-9-flash", "gemini-9-flash"], [8]))
                calls.clear()
                gemini.generate_best("k" * 30, "plan", "s", "u", sleep=sleeps.append)
                self.assertEqual(calls, ["gemini-9-flash"])  # the used-up model is not asked again today
            gemini._exhausted.clear()

    def test_rejected_key_stops_immediately(self):
        from chutku import gemini
        result, calls, _ = self.run_with([401])
        self.assertIsInstance(result, gemini.GeminiUnavailable)
        self.assertEqual(calls, ["gemini-9-pro"])


class BuildToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))
        self.runtime.capability_grants.grant("process.launch")
        self.vscode = patch.object(builder, "open_in_vscode", return_value={"opened": True})
        self.vscode.start()

    def tearDown(self):
        self.vscode.stop()
        self.runtime.close()
        self.temp.cleanup()

    def build(self, coder, path="calc"):
        existed = (self.runtime.granted_root / path).exists()
        with patch.object(builder, "choose_coder", return_value=(coder, None)):
            waiting = self.runtime.run("code.build_project", {"request": "a calculator", "path": path},
                                       provenance="delegated", autonomy="auto_edits")
            self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")  # R3: always a click
            self.assertEqual((self.runtime.granted_root / path).exists(), existed)  # nothing written before it
            return self.runtime.approve(waiting["approval"]["token"])

    def test_repairs_from_real_test_failure_then_passes(self):
        coder = FakeCoder([FIX])
        done = self.build(coder)
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        self.assertIn("FAIL: test_add", coder.errors_seen[0])  # the real unittest output went back
        output = done["output"]
        self.assertEqual([a["passed"] for a in output["attempts"]], [False, True])
        self.assertIn("unit tests passed (1 tests)", output["checks"])
        self.assertIn("2 + 3 = 5", " ".join(output["checks"]))
        self.assertTrue((Path(output["folder"]) / builder.MARKER).exists())

    def test_a_repair_that_rewrites_the_failing_test_is_discarded(self):
        cheat = ("PLAN: make the test match\n=== FILE: test_app.py ===\nimport unittest\nfrom calc import add\n\n\n"
                 "class T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), -1)\n"
                 "=== END FILE ===\n")
        coder = FakeCoder([cheat, FIX])
        done = self.build(coder)
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        attempts = done["output"]["attempts"]
        self.assertEqual([a["passed"] for a in attempts], [False, False, True])  # the cheat did not make it pass
        self.assertEqual(attempts[0]["discarded_test_edits"], ["test_app.py"])
        self.assertIn("was discarded: fix the program first", coder.errors_seen[1])  # the coder is told why
        test_file = (Path(done["output"]["folder"]) / "test_app.py").read_text(encoding="utf-8")
        self.assertIn("add(2, 3), 5", test_file)  # the original goal is untouched

    def test_a_wrong_generated_test_can_still_be_fixed_on_the_next_repair(self):
        right_test = ("PLAN: the test expected the wrong sum\n=== FILE: test_app.py ===\nimport unittest\n"
                      "from calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n"
                      "        self.assertEqual(add(2, 3), -1)\n=== END FILE ===\n")
        coder = FakeCoder([right_test, right_test])   # the program subtracts and its test insists: -1 is "right"
        done = self.build(coder)
        attempts = done["output"]["attempts"]
        self.assertEqual([a["passed"] for a in attempts], [False, False, True])
        self.assertEqual(attempts[1]["changed_own_tests"], ["test_app.py"])  # said openly in the build output

    def test_the_production_checklist_names_what_is_missing(self):
        import tempfile as _t
        with _t.TemporaryDirectory() as temp:
            folder = Path(temp)
            self.assertEqual(len(builder.production_checklist(folder, {"kind": "cli"})), 2)   # no README, no tests
            (folder / "README.md").write_text("x", encoding="utf-8")
            (folder / "test_app.py").write_text("x", encoding="utf-8")
            self.assertEqual(builder.production_checklist(folder, {"kind": "cli"}), [])
            (folder / "index.html").write_text('<script src="https://cdn.example/lib.js"></script>', encoding="utf-8")
            (folder / "app.css").write_text("@import url('//fonts.example/x.css');", encoding="utf-8")
            problems = builder.production_checklist(folder, {"kind": "web"})
            self.assertEqual(len(problems), 2)
            self.assertTrue(all("another site" in p for p in problems))
            (folder / "index.html").write_text('<script src="app.js"></script><a href="https://example.com">x</a>',
                                               encoding="utf-8")
            (folder / "app.css").write_text("body{}", encoding="utf-8")
            self.assertEqual(builder.production_checklist(folder, {"kind": "web"}), [])   # a plain link is fine

    def test_test_files_may_change_when_no_assertion_failed(self):
        files = {"test_app.py": "x", "calc.py": "y"}
        self.assertEqual(builder.keep_tests_fixed(files, "ERROR: test_add\nImportError: no module named calc"),
                         (files, []))
        self.assertEqual(builder.keep_tests_fixed(files, "Unit tests failed:\nFAIL: test_add (test_app.T.test_add)"),
                         ({"calc.py": "y"}, ["test_app.py"]))

    def test_gemini_outage_falls_back_to_the_local_coder_and_says_so(self):
        from chutku.gemini import GeminiUnavailable

        class DownGemini:
            name, model = "gemini", None

            def write(self, request):
                raise GeminiUnavailable("Gemini unavailable (HTTP 503).", status=503)
        local = FakeCoder([FIX])
        local.name = "local"
        with patch("chutku.coder.LocalCoder", return_value=local), patch("chutku.brain_service.shared_service"):
            done = self.build(DownGemini())
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        self.assertEqual(done["output"]["coder"], "local")
        self.assertIn("Gemini was unavailable", done["output"]["note"])

    def test_never_claims_success_when_checks_keep_failing(self):
        done = self.build(FakeCoder([]))
        self.assertEqual(str(done["state"]), "FAILED")
        self.assertEqual(len(done["output"]["attempts"]), builder.MAX_REPAIRS + 1)

    def test_existing_folder_is_never_overwritten(self):
        existing = self.runtime.granted_root / "calc"
        existing.mkdir()
        (existing / "mine.txt").write_text("owner's work")
        done = self.build(FakeCoder([FIX]))
        self.assertEqual(Path(done["output"]["folder"]).name, "calc-2")
        self.assertEqual((existing / "mine.txt").read_text(), "owner's work")

    def test_protected_and_out_of_grant_folders_are_refused(self):
        for path in (r"C:\Windows\calc", r"C:\Program Files\calc", str(PROJECT_ROOT / "data" / "calc")):
            result = self.runtime.run("code.build_project", {"request": "a calculator", "path": path})
            self.assertIn(str(result["state"]), {"FAILED", "DENIED"}, path)
            self.assertFalse(Path(path).exists(), path)

    def test_without_process_launch_capability_it_is_denied(self):
        self.runtime.capability_grants.revoke("process.launch")
        result = self.runtime.run("code.build_project", {"request": "a calculator", "path": "calc"})
        self.assertEqual(str(result["state"]), "DENIED")


class VSCodeEnvTests(unittest.TestCase):
    def test_electron_node_mode_from_a_parent_vscode_is_not_inherited(self):
        with patch.dict("os.environ", {"ELECTRON_RUN_AS_NODE": "1", "VSCODE_PID": "1", "KEEP_ME": "x"}):
            env = builder.vscode_env()
        self.assertNotIn("ELECTRON_RUN_AS_NODE", env)
        self.assertNotIn("VSCODE_PID", env)
        self.assertEqual(env["KEEP_ME"], "x")


class CoderChoiceTests(unittest.TestCase):
    def test_gemini_needs_grant_and_key(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "data").mkdir()
            self.assertIsNone(builder.gemini_allowed(Path(temp)))  # no cloud.gemini grant


class ProgressTests(unittest.TestCase):
    def tearDown(self):
        progress.set_hook()

    def test_beat_refreshes_and_stop_cancels(self):
        beats, stopped = [], [False]
        progress.set_hook(lambda: beats.append(1), lambda: stopped[0])
        progress.beat("writing")
        self.assertEqual(len(beats), 1)
        stopped[0] = True
        with self.assertRaises(progress.Cancelled):
            progress.beat()


if __name__ == "__main__":
    unittest.main()

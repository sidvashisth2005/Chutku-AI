"""Evolve (master plan Y2): review -> proposals -> owner-only approval -> apply in a git worktree, behind a boundary.

Fake coders, temporary git repositories and temporary data only: never the real repo or the owner's data.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from chutku import evolve, evolve_apply, reflex
from chutku.app import create_runtime
from chutku.core.preferences import Preferences
from chutku.quick_intents import quick_proposal
from chutku.router.catalog import CommandCatalog

PHRASE = "zorblat status dikhao"


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def iso(at):
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class FakeCoder:
    """Returns fixed files; ``repairs`` answer each later fix() call (the last one repeats)."""
    name, model = "fake", "fake-1"

    def __init__(self, first, repairs=()):
        self.first, self.repairs, self.calls = first, list(repairs), []

    def fix(self, request, files, errors):
        self.calls.append({"files": sorted(files), "errors": errors})
        if len(self.calls) == 1:
            return {"plan": "fake", "files": dict(self.first)}
        return {"plan": "fix", "files": dict(self.repairs[min(len(self.calls) - 2, len(self.repairs) - 1)]
                                              if self.repairs else self.first)}


class EvolveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        (self.base / "data").mkdir(parents=True)
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            runtime.close()
        self.temp.cleanup()

    def runtime(self):
        runtime = create_runtime(self.base)
        runtime.capability_grants.grant("process.launch")
        self.runtimes.append(runtime)
        return runtime

    def week(self):
        """A synthetic week: model-planned repeats, a failing tool, slow sessions, Hindi speech, refused asks."""
        now, data = time.time(), self.base / "data"
        turns = [{"at": now - 3600 * (i + 1), "origin": "text", "said": PHRASE, "reply": "ok", "status": "done",
                  "tools": ["system.environment"], "planners": ["local"]} for i in range(3)]
        turns += [{"at": now - 7200 * (i + 1) - 60, "origin": "text", "said": "zorblat ka graph banao", "reply": "?",
                   "status": "failed", "tools": [], "planners": ["local"]} for i in range(2)]
        turns.append({"at": now - 9 * 86400, "origin": "text", "said": "very old", "status": "done", "tools": ["x"],
                      "planners": ["local"]})
        turns.append({"at": now - 50, "origin": "script", "said": "script check", "status": "done", "tools": []})
        jsonl(data / "conversations.jsonl", sorted(turns, key=lambda t: t["at"]))
        jsonl(data / "experience.jsonl", [{"goal": PHRASE, "steps": [{"tool": "system.environment", "arguments": {},
                                                                     "purpose": "Read the system status"}],
                                           "at": now - 3600, "planners": ["local"], "replayable": False}])
        actions = [{"time": iso(now - 5000 - i), "tool": "windows.manage", "state": "FAILED",
                    "message": (f"No window titled \"Secret {i}\" at C:\\Users\\me\\x.txt" if i % 2 else
                                "No chat is named exactly 'Secret Person'; don't guess"), "approved_on_screen": False}
                   for i in range(4)]
        actions += [{"time": iso(now - 6000 - i), "tool": "filesystem.write_text", "state": "DENIED",
                     "message": "Cancelled on screen.", "approved_on_screen": False} for i in range(3)]
        actions += [{"time": iso(now - 8000), "tool": "apps.launch", "state": "COMPLETED", "session": "s1",
                     "arguments": {"name": "Spotify"}, "approved_on_screen": False},
                    {"time": iso(now - 7980), "tool": "media.play", "state": "COMPLETED", "session": "s1",
                     "approved_on_screen": False}]
        actions.append({"time": iso(now - 60), "tool": "filesystem.recycle", "state": "FAILED", "message": "script",
                        "approved_on_screen": False})   # ends in the script's turn: not the owner's week
        jsonl(data / "actions.log.jsonl", actions)
        jsonl(data / "heard.jsonl", [{"at": now - 100 * i, "path": "live", "text": "स्पॉटिफाई खोलो",
                                      "decision": "task: open spotify"} for i in range(6)]
              + [{"at": now - 900, "path": "live", "text": "hmm", "decision": "ignored"}])
        jsonl(data / "voice-timings.jsonl", [{"at": now - 400, "goal": "Open sport.", "seconds_to_first_audio": 21.0}])
        return now

    # -- 1. review --------------------------------------------------------------------------------------------
    def test_review_finds_the_evidence_and_never_changes_code(self):
        self.week()
        found = evolve.evidence(self.base)
        self.assertEqual(found["failed_or_unverified_steps"]["windows.manage"]["failed"], 4)
        self.assertNotIn("filesystem.recycle", found["failed_or_unverified_steps"])   # a script's action
        examples = found["failed_or_unverified_steps"]["windows.manage"]["examples"]
        self.assertEqual(len(examples), 3)
        for example in examples:
            self.assertNotIn("Secret", example)                                      # quoted names redacted
            self.assertNotIn("C:\\Users", example)                                   # paths redacted
        self.assertIn("don't guess", examples[0])                                    # an apostrophe is not a quote
        self.assertEqual(found["could_be_instant"][0]["times"], 3)
        self.assertEqual(found["slow"]["sessions_over_15s"], 1)
        self.assertEqual(found["slow"]["voice_first_audio_over_15s"], 1)
        self.assertEqual(found["speech"]["devanagari_lines"], 6)
        self.assertEqual(found["always_same_answer_to_asks"]["filesystem.write_text"]["always"], "refused")
        self.assertEqual(found["habits"]["apps"], [("spotify", 1)])
        self.assertEqual(found["repeatedly_stuck"][0]["times"], 2)
        self.assertEqual(found["requests"], 5)   # the 9-day-old turn and the script's turn are not counted

    # -- 2. proposals ------------------------------------------------------------------------------------------
    def test_offline_proposals_are_full_plans_at_most_three_a_day(self):
        now = self.week()
        runtime = self.runtime()
        with patch.object(evolve, "_cloud_drafter", side_effect=AssertionError("offline: no cloud")):
            out = evolve.review(self.base, runtime.registry, drafter=None)
        self.assertEqual(len(out["new_proposals"]), 3)
        self.assertEqual(out["drafted_by"], ["template"])
        proposals = evolve.load_all(self.base)
        self.assertEqual({p["kind"] for p in proposals}, {"preference", "code", "phrase"})   # strongest evidence first
        for p in proposals:
            for key in ("title", "evidence", "change", "steps", "tests", "risk", "undo", "payload"):
                self.assertTrue(p[key], (p["kind"], key))
            self.assertTrue(p["evidence"]["count"] and p["evidence"]["summary"])
            self.assertTrue(p["change"]["areas"] and p["tests"]["real_check"])
            self.assertEqual(p["status"], "proposed")
            text = evolve.describe(p)
            for word in ("Why:", "Changes:", "Step 1:", "Tests:", "Risk:", "Undo:", f"evolve approve {p['id']}"):
                self.assertIn(word, text)
        code = next(p for p in proposals if p["kind"] == "code")
        self.assertEqual(code["change"]["areas"], ["chutku/tools/everyday.py"])
        self.assertTrue((self.base / "data" / "evolve" / f"review-{datetime.now():%Y%m%d}.json").is_file())
        self.assertEqual(evolve.review(self.base, runtime.registry, drafter=None)["new_proposals"], [])   # cap: 3/day
        tomorrow = evolve.review(self.base, runtime.registry, drafter=None, now=now + 86400)
        self.assertEqual([evolve.load_proposal(self.base, i)["kind"] for i in tomorrow["new_proposals"]], ["skill"])

    def test_a_cloud_draft_only_refines_code_steps_and_sees_redacted_text(self):
        self.week()
        seen = []

        def drafter(summary):
            seen.append(summary)
            return "STEP: look at the window matcher\nSTEP: match titles case-insensitively\nTEST: a title test"
        evolve.review(self.base, self.runtime().registry, drafter=drafter)
        code = next(p for p in evolve.load_all(self.base) if p["kind"] == "code")
        self.assertEqual(code["drafted_by"], "gemini")
        self.assertEqual(code["steps"][1], "match titles case-insensitively")
        self.assertEqual(code["change"]["areas"], ["chutku/tools/everyday.py"])   # the cloud cannot move the area
        self.assertNotIn("Secret", seen[0])
        self.assertNotIn("Users", seen[0])

    def test_protected_tools_get_no_code_proposal(self):
        found = {"failed_or_unverified_steps": {"skill.list": {"failed": 9, "unverified": 0, "examples": []}}}
        self.assertEqual(evolve._code_candidates(found, self.runtime().registry, None), [])   # chutku/skills.py

    # -- 3. owner decision --------------------------------------------------------------------------------------
    def phrase_proposal(self):
        self.week()
        evolve.review(self.base, self.runtime().registry, drafter=None)
        (self.base / "data" / "actions.log.jsonl").unlink()   # synthetic rows have no hash chain for the runtime
        return next(p for p in evolve.load_all(self.base) if p["kind"] == "phrase")

    def test_approve_is_typed_by_the_owner_only(self):
        pid = self.phrase_proposal()["id"]
        runtime = self.runtime()
        tool = runtime.registry.get("evolve.approve")
        self.assertTrue(tool.user_only and tool.runs_code)
        for provenance, autonomy in (("delegated", "owner"), ("delegated", "trusted"),
                                     ("delegated_microphone", "owner"), ("inferred", None),
                                     ("microphone_untrusted", None)):
            result = runtime.run("evolve.approve", {"id": pid}, provenance=provenance, autonomy=autonomy)
            self.assertEqual(str(result["state"]), "DENIED", provenance)
        waiting = runtime.run("evolve.approve", {"id": pid}, provenance="reviewed_microphone")   # a voice plan
        if str(waiting["state"]) == "WAITING_CONFIRMATION":
            waiting = runtime.approve(waiting["approval"]["token"])
        self.assertNotEqual(str(waiting["state"]), "COMPLETED")
        self.assertEqual(evolve.load_proposal(self.base, pid)["status"], "proposed")
        self.assertEqual(CommandCatalog().route(f"evolve approve {pid}").tool_name, "evolve.approve")
        self.assertIsNone(quick_proposal(f"evolve approve {pid}"))   # the agent path has no approve phrase
        self.assertEqual(quick_proposal("khud ko improve karo")["next_steps"][0]["tool"], "evolve.review")
        self.assertEqual(quick_proposal("aaj ke suggestions")["next_steps"][0]["tool"], "evolve.list")
        self.assertEqual(quick_proposal("improvement ideas do")["next_steps"][0]["tool"], "evolve.review")

    def test_typed_approval_applies_a_phrase_and_reject_sticks(self):
        proposal = self.phrase_proposal()
        runtime = self.runtime()
        waiting = runtime.run("evolve.approve", {"id": proposal["id"]})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")   # typed, then a click
        done = runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        self.assertEqual(evolve.load_proposal(self.base, proposal["id"])["status"], "applied")
        found = reflex.match(self.base, PHRASE, runtime)
        self.assertEqual(found[0]["next_steps"][0]["tool"], "system.environment")   # now instant, no model
        preference = next(p for p in evolve.load_all(self.base) if p["kind"] == "preference")
        self.assertEqual(str(runtime.run("evolve.reject", {"id": preference["id"]})["state"]), "COMPLETED")
        self.assertEqual(Preferences(self.base).load()["stt_language"], "en")
        again = runtime.run("evolve.approve", {"id": preference["id"]})
        self.assertNotEqual(str(runtime.approve(again["approval"]["token"])["state"]), "COMPLETED")
        evolve.review(self.base, runtime.registry, drafter=None, now=time.time() + 86400)
        self.assertEqual(evolve.load_proposal(self.base, preference["id"])["status"], "rejected")   # never again
        history = (self.base / "data" / "evolve" / "history.jsonl").read_text(encoding="utf-8")
        self.assertIn('"applied"', history)
        self.assertIn('"rejected"', history)

    def test_a_preference_idea_outside_the_allowlist_is_refused(self):
        proposal = evolve._proposal("preference", "x", "Relax", {"summary": "s", "count": 1, "examples": []},
                                    {"lane": "data", "areas": ["data/preferences.json"], "detail": "d"}, ["s"],
                                    {"unit": ["u"], "real_check": "r"}, "r", "u",
                                    {"changes": {"earned_autonomy_relax": True}})
        evolve.save_proposal(self.base, proposal)
        out = evolve.approve(self.base, self.runtime().registry, proposal["id"])
        self.assertIn("error", out)
        self.assertFalse(Preferences(self.base).load()["earned_autonomy_relax"])

    # -- 4./5. the code lane in a temporary repository ---------------------------------------------------------------
    def repo(self):
        repo = Path(self.temp.name) / "repo"
        files = {"app/calc.py": "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
                 "tests/test_calc.py": "import unittest\nfrom app.calc import sub\n\n\nclass T(unittest.TestCase):\n"
                                       "    def test_sub(self):\n        self.assertEqual(sub(5, 3), 2)\n",
                 "scripts/check_phrases.py": "print('instant: 1/1  slowest match: 0.1 ms')\n",
                 "chutku/policy/kernel.py": "ALLOW = False\n"}
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8", newline="\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "start")
        return repo

    def checks(self):
        return [("unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"], 120),
                ("instant phrases", [sys.executable, "scripts/check_phrases.py"], 60)]

    def approved_code(self):
        proposal = evolve._proposal("code", "fix:calc", "Fix add", {"summary": "add failed 3 times", "count": 3,
                                                                   "examples": []},
                                    {"lane": "code", "areas": ["app/calc.py"], "detail": "code"},
                                    ["make add add"], {"unit": ["tests/test_improve.py"], "real_check": "add(2, 2)"},
                                    "medium", "git revert", {"request": "fix add"})
        evolve.save_proposal(self.base, proposal)
        started = []
        out = evolve.approve(self.base, self.runtime().registry, proposal["id"], start=lambda b, p: started.append(p))
        self.assertEqual((out["status"], started), ("approved", [proposal["id"]]))
        self.assertIn("GitHub push: off", out["skill_reply"])
        return proposal["id"]

    def gone(self, repo, pid):
        self.assertEqual(git(repo, "branch", "--list", f"evolve/{pid}"), "")
        self.assertFalse((self.base / "data" / "evolve" / "work" / pid).exists())
        self.assertNotIn(f"evolve/{pid}", git(repo, "worktree", "list"))

    FIXED = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
    NEW_TEST = ("import unittest\nfrom app.calc import add\n\n\nclass T(unittest.TestCase):\n    def test_add(self):\n"
                "        self.assertEqual(add(2, 2), {})\n")

    def test_a_passing_change_is_merged_into_main(self):
        repo, pid = self.repo(), self.approved_code()
        start = git(repo, "rev-parse", "HEAD")
        coder = FakeCoder({"app/calc.py": self.FIXED, f"tests/test_improve_{pid}.py": self.NEW_TEST.format(4)})
        out = evolve_apply.run(self.base, pid, repo=repo, coder=coder, checks=self.checks())
        self.assertEqual(out["status"], "merged", out)
        self.assertEqual(git(repo, "rev-parse", "HEAD^"), start)   # a fast-forward of one commit on main
        message = git(repo, "log", "-1", "--format=%B")
        self.assertEqual(message, f"Evolve {pid}: Fix add")
        self.assertNotIn("Co-Authored-By", message)
        self.assertEqual((repo / "app" / "calc.py").read_text(encoding="utf-8"), self.FIXED)
        self.assertEqual(out["details"]["pushed"], "off (preference evolve_push)")
        self.assertEqual(out["details"]["baseline"]["unit tests"]["count"], 1)
        self.assertEqual(out["details"]["attempts"][-1]["checks"]["unit tests"]["count"], 2)
        self.gone(repo, pid)
        saved = evolve.load_proposal(self.base, pid)
        self.assertEqual(saved["status"], "merged")
        self.assertIn("git revert", saved["result"])

    def test_a_failing_change_leaves_main_untouched_and_the_branch_removed(self):
        repo, pid = self.repo(), self.approved_code()
        start = git(repo, "rev-parse", "HEAD")
        wrong = {"app/calc.py": self.FIXED.replace("a + b", "a * b"), f"tests/test_improve_{pid}.py":
                 self.NEW_TEST.format(5)}
        coder = FakeCoder(wrong)
        out = evolve_apply.run(self.base, pid, repo=repo, coder=coder, checks=self.checks())
        self.assertEqual(out["status"], "failed", out)
        self.assertEqual(len(coder.calls), 1 + evolve_apply.MAX_REPAIRS)   # first write + 3 repairs
        self.assertIn("FAIL: test_add", coder.calls[1]["errors"])          # real error output went back
        self.assertEqual(git(repo, "rev-parse", "HEAD"), start)
        self.assertEqual(git(repo, "status", "--porcelain"), "")
        self.gone(repo, pid)
        self.assertEqual(evolve.load_proposal(self.base, pid)["status"], "failed")

    def test_a_diff_touching_policy_is_refused_and_discarded(self):
        repo, pid = self.repo(), self.approved_code()
        start = git(repo, "rev-parse", "HEAD")
        coder = FakeCoder({"app/calc.py": self.FIXED, "chutku/policy/kernel.py": "ALLOW = True\n"})
        out = evolve_apply.run(self.base, pid, repo=repo, coder=coder, checks=self.checks())
        self.assertEqual(out["status"], "refused", out)
        self.assertIn("chutku/policy/kernel.py", out["result"])
        self.assertEqual(git(repo, "rev-parse", "HEAD"), start)
        self.assertEqual((repo / "chutku" / "policy" / "kernel.py").read_text(encoding="utf-8"), "ALLOW = False\n")
        self.gone(repo, pid)

    def test_a_change_to_an_existing_test_is_refused(self):
        repo, pid = self.repo(), self.approved_code()
        weakened = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_sub(self):\n        pass\n"
        out = evolve_apply.run(self.base, pid, repo=repo, coder=FakeCoder({"tests/test_calc.py": weakened}),
                               checks=self.checks())
        self.assertEqual(out["status"], "refused", out)
        self.assertIn("append-only", out["result"])
        self.gone(repo, pid)

    def test_only_an_approved_unchanged_plan_is_applied(self):
        repo, pid = self.repo(), self.approved_code()
        proposal = evolve.load_proposal(self.base, pid)
        proposal["steps"].append("also relax the policy")   # edited after the owner approved it
        evolve.save_proposal(self.base, proposal)
        out = evolve_apply.run(self.base, pid, repo=repo, coder=FakeCoder({}), checks=self.checks())
        self.assertIn("not approved as it stands", out["error"])

    # -- the boundary itself -----------------------------------------------------------------------------------------
    def test_boundary_rules(self):
        def change(status="M", added=(), removed=()):
            return {"status": status, "added": list(added), "removed": list(removed), "binary": False}
        check = evolve_apply.check
        self.assertEqual(check({"chutku/quick_intents.py": change(added=["    return 1"])}), [])
        for path in ("chutku/policy/kernel.py", "chutku/runtime.py", "chutku/core/paths.py", "chutku/guard.py",
                     "chutku/tools/registry.py", "chutku/skills.py", "chutku/evolve.py", "chutku/evolve_apply.py",
                     "AGENTS.md", "docs/SECURITY.md", "tests/test_docs_truth.py", "tests/test_trusted_task.py",
                     "tests/test_autonomy_policy.py", "tests/test_protected_zones.py", "tests/test_taint_v2.py",
                     "tests/test_elevation.py", "tests/test_injection_s15.py", "tests/test_failclosed_s3.py",
                     "tests/test_evolve_y2.py", ".github/workflows/ci.yml", "requirements.lock", "pyproject.toml",
                     "CHUTKU/Policy/Kernel.py", "chutku\\core\\ledger.py", "chutku/dashboard_voice.py",
                     "chutku/dashboard_work.py", "chutku/remote/streams.py"):
            self.assertTrue(check({path: change(added=["x = 1"])}), path)
            self.assertTrue(evolve_apply.protected(path), path)
        self.assertIn("deletes", check({"tests/test_calc.py": change("D", removed=["def test_a(self):"])})[0])
        relabel = change(added=["    Risk.OBSERVATION, run,"], removed=["    Risk.DESTRUCTIVE_OR_PRIVILEGED, run,"])
        self.assertTrue(check({"chutku/tools/everyday.py": relabel}))
        self.assertTrue(check({"chutku/tools/everyday.py": change(added=["import subprocess"])}))
        self.assertTrue(check({"chutku/apps/atlas/vlc.json": change(added=['   "risk": "safe",'])}))
        self.assertTrue(check({"tests/test_new.py": change("A", added=["@unittest.skip('no')"])}))
        self.assertTrue(check({"chutku/a.py": change(added=["x"] * 401)}))
        self.assertTrue(check({f"chutku/m{i}.py": change(added=["x"]) for i in range(9)}))
        self.assertEqual(check({"tests/test_new.py": change("A", added=["def test_x(self):", "    assert 1"])}), [])


if __name__ == "__main__":
    unittest.main()

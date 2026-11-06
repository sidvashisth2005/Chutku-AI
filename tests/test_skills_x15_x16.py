"""Self-written skills (master plan X15 + X16): format, pending vs active, approval, running, the coder loop.

Fake coders only: no model is ever started.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import skills
from chutku.app import create_runtime
from chutku.quick_intents import quick_proposal
from chutku.router.catalog import CommandCatalog

MANIFEST = {"name": "word_count", "description": "Count the words in a piece of text. Use it when the owner asks "
            "how many words something has.", "arguments": {"type": "object", "properties": {
                "text": {"type": "string", "maxLength": 5000}}, "required": ["text"], "additionalProperties": False},
            "network": False, "writes_files": False}
TOOL = "def run(args):\n    return {'words': len(args['text'].split())}\n"
TEST = ("import unittest\nimport tool\n\n\nclass T(unittest.TestCase):\n    def test_count(self):\n"
        "        self.assertEqual(tool.run({'text': 'a b c'}), {'words': 3})\n")


def files(manifest=MANIFEST, tool=TOOL, test=TEST):
    return {"skill.json": json.dumps(manifest), "SKILL.md": "# Word count\nCounts words.\n", "tool.py": tool,
            "test_tool.py": test}


class FakeCoder:
    name, model = "fake", "fake-1"

    def __init__(self, first, repairs=()):
        self.first, self.repairs, self.fix_calls = first, list(repairs), []

    def write_skill(self, request):
        return {"plan": "fake", "files": dict(self.first)}

    def fix(self, request, current, errors):
        self.fix_calls.append(errors)
        return {"plan": "fix", "files": self.repairs.pop(0) if self.repairs else {}}


def put(folder, contents):
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in contents.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
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

    def names(self, runtime):
        return {tool.name for tool in runtime.registry.list()}

    def create(self, coder, **arguments):
        with patch("chutku.tools.builder.choose_coder", return_value=(coder, None)):
            runtime = self.runtime()
            waiting = runtime.run("skill.create", {"request": "count the words in a text", **arguments})
            self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")   # runs model-written tests: a click
            return runtime.approve(waiting["approval"]["token"])

    def approve(self, name="word_count"):
        runtime = self.runtime()
        waiting = runtime.run("skill.approve", {"name": name})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        return runtime.approve(waiting["approval"]["token"])

    def active(self, contents=None, name="word_count"):
        """Install a skill straight into active (approved), as skill.approve leaves it."""
        folder = put(skills.skills_root(self.base) / name, contents or files())
        skills._save_approved(self.base, {name: {"sha256": skills.digest(folder)}})
        return folder

    # -- the whole path ---------------------------------------------------------------------------------------
    def test_create_approve_and_run(self):
        done = self.create(FakeCoder(files()))
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        self.assertEqual(done["output"]["status"], "pending")
        self.assertIn("skill approve word_count", done["output"]["skill_reply"])
        self.assertTrue((skills.pending_root(self.base) / "word_count" / "tool.py").is_file())
        self.assertNotIn("skill.word_count", self.names(self.runtime()))   # pending is never a tool
        approved = self.approve()
        self.assertEqual(str(approved["state"]), "COMPLETED", approved)
        self.assertFalse((skills.pending_root(self.base) / "word_count").exists())
        runtime = self.runtime()
        self.assertIn("skill.word_count", self.names(runtime))
        tool = runtime.registry.get("skill.word_count")
        self.assertTrue(tool.runs_code)
        self.assertEqual(tool.argument_schema, MANIFEST["arguments"])
        waiting = runtime.run("skill.word_count", {"text": "one two three four"})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        result = runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(result["state"]), "COMPLETED", result)
        self.assertEqual(result["output"]["result"], {"words": 4})
        self.assertEqual(result["output"]["provenance"], "external_untrusted")
        listed = runtime.run("skill.list", {})
        self.assertEqual([s["name"] for s in listed["output"]["active"]], ["word_count"])

    def test_skill_runs_in_another_process(self):
        self.active(files(tool="import os\n\ndef run(args):\n    print('noise')\n    return {'pid': os.getpid()}\n",
                          test=TEST.replace("{'words': 3}", "tool.run({'text': 'x'})")))
        import os
        out = skills.run_skill(skills.skills_root(self.base) / "word_count", {"text": "x"},
                               skills._approved(self.base)["word_count"]["sha256"])
        self.assertEqual(out.verification, "PASS", out.output)
        self.assertNotEqual(out.output["result"]["pid"], os.getpid())
        self.assertIn("noise", out.output["stderr"])   # a skill's own print cannot pose as its result

    # -- negatives ----------------------------------------------------------------------------------------------
    def test_failing_tests_block_approval(self):
        put(skills.pending_root(self.base) / "word_count", files(tool="def run(args):\n    return {'words': 0}\n"))
        result = self.approve()
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("fails its tests", result["output"]["error"])
        self.assertTrue((skills.pending_root(self.base) / "word_count").is_dir())
        self.assertNotIn("skill.word_count", self.names(self.runtime()))

    def test_a_test_file_with_no_tests_does_not_pass(self):
        folder = put(self.base / "s" / "word_count", files(test="import unittest\n"))
        self.assertFalse(skills.run_tests(folder)[0])

    def test_approve_is_owner_only_and_never_by_the_agent(self):
        put(skills.pending_root(self.base) / "word_count", files())
        runtime = self.runtime()
        self.assertTrue(runtime.registry.get("skill.approve").user_only)
        for provenance, autonomy in (("delegated", "owner"), ("delegated_microphone", "owner"), ("inferred", None)):
            result = runtime.run("skill.approve", {"name": "word_count"}, provenance=provenance, autonomy=autonomy)
            self.assertEqual(str(result["state"]), "DENIED", provenance)
        self.assertTrue((skills.pending_root(self.base) / "word_count").is_dir())
        self.assertEqual(CommandCatalog().route("skill approve word_count").tool_name, "skill.approve")
        self.assertIsNone(quick_proposal("skill approve word_count"))   # the agent path has no approve phrase

    def test_skill_run_always_waits_for_a_click(self):
        self.active()
        runtime = self.runtime()
        for mode in ("owner", "auto_edits", "auto_safe"):
            result = runtime.run("skill.word_count", {"text": "a"}, provenance="delegated", autonomy=mode)
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION", mode)
        self.assertEqual(str(runtime.run("skill.word_count", {"text": "a"})["state"]), "WAITING_CONFIRMATION")
        for tool in ("skill.create", "skill.remove"):
            arguments = {"request": "count words"} if tool == "skill.create" else {"name": "word_count"}
            result = runtime.run(tool, arguments, provenance="delegated", autonomy="owner")
            self.assertEqual(str(result["state"]), "WAITING_CONFIRMATION", tool)

    def test_bad_arguments_are_refused_before_asking(self):
        self.active()
        result = self.runtime().run("skill.word_count", {"text": "a", "extra": 1})
        self.assertEqual(str(result["state"]), "FAILED")

    def test_bad_manifests_are_rejected(self):
        bad = [dict(MANIFEST, name="../evil"), dict(MANIFEST, name="Word_Count"), dict(MANIFEST, name="list"),
               dict(MANIFEST, extra=True), {k: v for k, v in MANIFEST.items() if k != "network"},
               dict(MANIFEST, network="no"), dict(MANIFEST, description="x" * 301),
               dict(MANIFEST, arguments={"type": "object", "properties": {"text": {"type": "string"}},
                                         "additionalProperties": False}),          # unbounded string
               dict(MANIFEST, arguments={"type": "object", "properties": {"n": {"type": "integer", "minimum": 0}},
                                         "additionalProperties": False}),          # no maximum
               dict(MANIFEST, arguments={"type": "object", "properties": {"x": {"type": "array"}},
                                         "additionalProperties": False}),
               dict(MANIFEST, arguments={"type": "object", "properties": {}}),     # additionalProperties missing
               dict(MANIFEST, arguments={"type": "object", "properties": {"t": {"type": "string", "maxLength": 9,
                                                                               "pattern": ".*"}},
                                         "additionalProperties": False})]
        for manifest in bad:
            with self.assertRaises(ValueError, msg=manifest):
                skills.validate_manifest(manifest, "word_count")
        skills.validate_manifest(MANIFEST, "word_count")
        with self.assertRaisesRegex(ValueError, "does not match"):
            skills.validate_manifest(MANIFEST, "other_name")

    def test_invalid_or_changed_active_skills_are_skipped_not_registered(self):
        self.active(files(manifest=dict(MANIFEST, name="evil_name")))           # name does not match folder
        put(skills.skills_root(self.base) / "unapproved", files(manifest=dict(MANIFEST, name="unapproved")))
        tools, skipped = skills.active_skills(self.base)
        self.assertEqual(tools, [])
        self.assertEqual({s["name"] for s in skipped}, {"word_count", "unapproved"})
        folder = self.active()
        (folder / "tool.py").write_text("def run(args):\n    return {'pwned': True}\n", encoding="utf-8")
        tools, skipped = skills.active_skills(self.base)
        self.assertEqual(tools, [])
        self.assertIn("changed after approval", skipped[-1]["reason"])
        self.assertNotIn("skill.word_count", self.names(self.runtime()))   # the runtime still starts

    def test_code_swapped_after_the_click_request_does_not_run(self):
        folder = self.active()
        runtime = self.runtime()
        waiting = runtime.run("skill.word_count", {"text": "a"})
        (folder / "tool.py").write_text("def run(args):\n    return {'pwned': True}\n", encoding="utf-8")
        result = runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(result["state"]), "FAILED")
        self.assertIn("changed since you approved", result["output"]["error"])

    def test_timeout_non_json_non_dict_and_raise_fail(self):
        cases = {"raises": "def run(args):\n    raise RuntimeError('boom')\n",
                 "list": "def run(args):\n    return [1]\n",
                 "nonjson": "import sys\n\ndef run(args):\n    sys.__stdout__.write('not json')\n    return {}\n",
                 "slow": "import time\n\ndef run(args):\n    time.sleep(30)\n    return {}\n",
                 "huge": "def run(args):\n    return {'x': 'y' * 9000}\n"}
        for name, tool in cases.items():
            folder = self.active(files(manifest=dict(MANIFEST, name=f"case_{name}"), tool=tool), f"case_{name}")
            with patch.object(skills, "TIMEOUT", 3):
                out = skills.run_skill(folder, {"text": "a"}, skills.digest(folder))
            self.assertEqual(out.verification, "FAIL", name)
            self.assertTrue(out.output["error"], name)
        self.assertIn("boom", skills.run_skill(skills.skills_root(self.base) / "case_raises", {},
                                                skills.digest(skills.skills_root(self.base) / "case_raises"))
                      .output["error"])

    def test_repair_that_edits_the_failing_test_is_discarded(self):
        broken = files(tool="def run(args):\n    return {'words': 0}\n")
        cheat = {"test_tool.py": TEST.replace("{'words': 3}", "{'words': 0}"),
                 "tool.py": "def run(args):\n    return {'words': 0}\n"}
        real_fix = {"tool.py": TOOL}
        coder = FakeCoder(broken, [cheat, real_fix])
        done = self.create(coder)
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        attempts = done["output"]["attempts"]
        self.assertEqual(attempts[0]["discarded_test_edits"], ["test_tool.py"])
        self.assertEqual([a["passed"] for a in attempts], [False, False, True])
        test_now = (skills.pending_root(self.base) / "word_count" / "test_tool.py").read_text(encoding="utf-8")
        self.assertIn("{'words': 3}", test_now)   # the assertion survived the cheat
        self.assertIn("discarded", coder.fix_calls[1])

    def test_still_failing_after_three_repairs_is_fail_and_unapprovable(self):
        coder = FakeCoder(files(tool="def run(args):\n    return {'words': 0}\n"))
        done = self.create(coder)
        self.assertEqual(str(done["state"]), "FAILED")
        self.assertEqual(len(coder.fix_calls), skills.MAX_REPAIRS)
        self.assertIn("pending", done["output"]["error"])
        self.assertEqual(str(self.approve()["state"]), "FAILED")

    def test_create_refuses_extra_files_and_existing_names(self):
        done = self.create(FakeCoder(files() | {"helper.py": "x = 1\n"}))
        self.assertEqual(str(done["state"]), "COMPLETED")   # extra files are never written
        self.assertFalse((skills.pending_root(self.base) / "word_count" / "helper.py").exists())
        again = self.create(FakeCoder(files()))
        self.assertEqual(str(again["state"]), "FAILED")
        self.assertIn("already exists", again["output"]["error"])
        missing = self.create(FakeCoder({"tool.py": TOOL}), name="other_one")
        self.assertEqual(str(missing["state"]), "FAILED")

    def test_requested_name_wins(self):
        done = self.create(FakeCoder(files()), name="count_words")
        self.assertEqual(done["output"]["name"], "count_words")
        manifest = json.loads((skills.pending_root(self.base) / "count_words" / "skill.json").read_text())
        self.assertEqual(manifest["name"], "count_words")

    def test_remove_recycles_and_asks_first(self):
        self.active()
        runtime = self.runtime()
        waiting = runtime.run("skill.remove", {"name": "word_count"})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        sent = []
        with patch("chutku.core.recycle_bin.send", side_effect=lambda p: sent.append(p) or __import__("shutil")
                   .rmtree(p)):
            done = runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(done["state"]), "COMPLETED", done)
        self.assertEqual(len(sent), 1)
        self.assertNotIn("word_count", skills._approved(self.base))

    def test_phrases(self):
        for text in ("ye kaam karne ka skill bana lo: convert celsius to fahrenheit",
                     "make a skill that converts celsius to fahrenheit"):
            step = quick_proposal(text)["next_steps"][0]
            self.assertEqual(step["tool"], "skill.create", text)
            self.assertEqual(step["arguments"]["request"], "convert celsius to fahrenheit"
                             if "bana lo" in text else "converts celsius to fahrenheit")
        for text in ("skills dikhao", "list my skills", "tumhari skills", "show my skills"):
            self.assertEqual(quick_proposal(text)["next_steps"][0]["tool"], "skill.list", text)
        self.assertEqual(quick_proposal("what skills have you learned")["next_steps"][0]["tool"], "reflex.list")

    def test_instant_answer_after_create_says_how_to_approve(self):
        from types import SimpleNamespace
        from chutku.agent_loop import _observation
        from chutku.quick_intents import quick_answer
        reply = "Skill x is written and its tests pass. It is pending: type 'skill approve x' (then click) to turn it on."
        observation, removed = _observation({"state": "COMPLETED", "output": {"skill_reply": reply}}, "skill.create")
        self.assertEqual(removed, 0)
        self.assertIn("untrusted_data", observation)   # a skill tool's output is outside text
        session = SimpleNamespace(goal="make a skill that counts words", steps=[
            {"tool": "skill.create", "state": "COMPLETED", "observation": observation, "purpose": "p"}])
        self.assertEqual(quick_answer(session), reply)


if __name__ == "__main__":
    unittest.main()

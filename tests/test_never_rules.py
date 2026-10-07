"""The owner's never-rules (Phase 3b H1): refused in every mode, before any other rule; an approval cannot
override them; adding is instant, removing always asks; an unreadable rules file fails closed."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from chutku import mind
from chutku.app import create_runtime
from chutku.policy import never_rules
from chutku.policy.kernel import Decision, PolicyKernel
from chutku.router.catalog import CommandCatalog


class NeverRuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "state"
        self.mind_root = patch.object(mind, "PROJECT_ROOT", self.base)
        self.mind_root.start()
        self.runtime = create_runtime(self.base)
        self.root = self.runtime.granted_root
        self.exams = self.root / "Exams"
        self.exams.mkdir()
        (self.exams / "paper.txt").write_text("old", encoding="utf-8")

    def tearDown(self):
        self.runtime.close()
        self.mind_root.stop()
        self.temp.cleanup()

    def rule(self, kind, pattern):
        return never_rules.add_rule(self.base, kind, pattern)

    def run_step(self, tool, arguments, autonomy="owner"):
        return self.runtime.run(tool, arguments, provenance="delegated", autonomy=autonomy, tainted=False,
                                exposed=False)

    def test_path_rule_refuses_reads_and_writes_inside_in_every_mode(self):
        self.rule("path", str(self.exams))
        for mode in ("owner", "auto_edits", "auto_safe", "review"):
            for tool, args in (("filesystem.write_text", {"path": str(self.exams / "paper.txt"), "content": "new"}),
                               ("filesystem.read_text", {"path": "Exams/paper.txt"}),
                               ("filesystem.list", {"path": str(self.exams).upper()})):
                result = self.run_step(tool, args, mode)
                self.assertEqual(str(result["state"]), "DENIED", (tool, mode, result))
                self.assertIn("kabhi nahi", result["reason"])
                self.assertNotIn("approval", result)
        self.assertEqual((self.exams / "paper.txt").read_text(encoding="utf-8"), "old")

    def test_outside_the_rule_is_untouched(self):
        self.rule("path", str(self.exams))
        other = self.root / "Exams2"   # a sibling whose name starts the same is not inside
        other.mkdir()
        result = self.run_step("filesystem.list", {"path": str(other)})
        self.assertNotEqual(str(result["state"]), "DENIED", result)

    def test_approval_cannot_override_and_a_rule_added_after_the_card_still_wins(self):
        script = self.root / "hello.py"
        script.write_text("print('hello')\n", encoding="utf-8")
        self.runtime.capability_grants.grant("process.launch")
        waiting = self.run_step("code.run_python", {"path": str(script)})
        self.assertEqual(str(waiting["state"]), "WAITING_CONFIRMATION")
        self.rule("command", "hello")   # the owner adds a rule before clicking approve
        done = self.runtime.approve(waiting["approval"]["token"])
        self.assertEqual(str(done["state"]), "DENIED", done)

    def test_command_rule_reads_the_script_text(self):
        script = self.root / "job.py"
        script.write_text("print('zz forbidden phrase zz')\n", encoding="utf-8")
        self.rule("command", "forbidden phrase")
        kernel = PolicyKernel()
        tool = self.runtime.registry.get("code.run_python")
        reason = never_rules.floor_reason(tool, {"path": "job.py"}, granted_root=self.root, base=self.base)
        self.assertIn("forbidden phrase", reason)
        decision = kernel.authorize(tool, {"path": "job.py"}, True, provenance="delegated", autonomy="owner",
                                    tainted=False, exposed=False, floor_reason=reason)
        self.assertEqual(decision.decision, Decision.DENY)

    def test_tool_rule_and_never_tools_are_exempt(self):
        self.rule("tool", "web.*")
        tool = self.runtime.registry.get("web.open")
        self.assertIsNotNone(never_rules.floor_reason(tool, {"url": "https://example.com"}, base=self.base))
        self.rule("tool", "never.*")
        listing = self.runtime.run("never.list", {})
        self.assertEqual(str(listing["state"]), "COMPLETED", listing)

    def test_unreadable_rules_file_fails_closed_for_changes(self):
        never_rules.rules_path(self.base).write_text("{not json", encoding="utf-8")
        write = self.runtime.registry.get("filesystem.write_text")
        read = self.runtime.registry.get("system.get_time")
        self.assertIsNotNone(never_rules.floor_reason(write, {"path": "a.txt", "content": "x"}, base=self.base))
        self.assertIsNone(never_rules.floor_reason(read, {}, base=self.base))   # looking is still allowed

    def test_add_is_instant_remove_always_asks_and_the_agent_can_do_neither(self):
        added = self.runtime.run("never.add", {"kind": "path", "pattern": str(self.exams)})
        self.assertEqual(str(added["state"]), "COMPLETED", added)
        rule_id = never_rules.load_rules(self.base)[0]["id"]
        for mode in ("owner", "auto_edits"):
            asked = self.run_step("never.remove", {"id": rule_id}, mode)
            self.assertNotEqual(str(asked["state"]), "COMPLETED", (mode, asked))
        self.assertEqual(len(never_rules.load_rules(self.base)), 1)
        agent_add = self.run_step("never.add", {"kind": "tool", "pattern": "x.*"})
        self.assertEqual(str(agent_add["state"]), "DENIED")   # user_only: the agent never chooses rules
        direct = self.runtime.run("never.remove", {"id": rule_id})
        self.assertEqual(str(direct["state"]), "WAITING_CONFIRMATION")
        self.assertEqual(str(self.runtime.approve(direct["approval"]["token"])["state"]), "COMPLETED")
        self.assertEqual(never_rules.load_rules(self.base), [])

    def test_duplicates_and_bad_paths(self):
        first = self.rule("path", str(self.exams))
        again = self.rule("path", str(self.exams).lower())
        self.assertEqual(first["id"], again["id"])
        with self.assertRaises(ValueError):
            self.rule("path", "Exams")   # a path rule needs a full path


class PhraseTests(unittest.TestCase):
    def test_phrases_route_to_the_rule_tools(self):
        catalog = CommandCatalog()
        cases = {r"never touch D:\Exams": ("never.add", {"kind": "path", "pattern": r"D:\Exams"}),
                 r"D:\Exams ko kabhi mat chhoona": ("never.add", {"kind": "path", "pattern": r"D:\Exams"}),
                 r"kabhi bhi D:\Study\private ko mat chhedna": ("never.add", {"kind": "path",
                                                                              "pattern": r"D:\Study\private"}),
                 "never use tool message.send": ("never.add", {"kind": "tool", "pattern": "message.send"}),
                 "never rules": ("never.list", {}), "mere never rules dikhao": ("never.list", {}),
                 "remove never rule a1b2c3": ("never.remove", {"id": "a1b2c3"}),
                 "never rule a1b2c3 hatao": ("never.remove", {"id": "a1b2c3"})}
        for text, (tool, arguments) in cases.items():
            routed = catalog.route(text)
            self.assertEqual((routed.tool_name, routed.arguments), (tool, arguments), text)


if __name__ == "__main__":
    unittest.main()

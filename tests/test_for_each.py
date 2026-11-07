"""H14: one for-each step repeats a tool for every item of an earlier step's list, under the same rules per item."""
import unittest

from chutku.agent_loop import AgentSession
from chutku.for_each import MAX_ITEMS, expand, select

from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with, real_registry

PDFS = {"query": "pdf", "count": 3, "matches": [
    {"path": "C:\\Users\\me\\Downloads\\a.pdf", "ext": ".pdf"},
    {"path": "C:\\Users\\me\\Downloads\\b.PDF", "ext": ".PDF"},
    {"path": "C:\\Users\\me\\Downloads\\notes.txt", "ext": ".txt"}]}
MOVE = {"tool": "filesystem.move", "arguments": {"source": "{item}",
                                                  "destination": "C:\\Users\\me\\Study\\{item_name}"}}


def for_each(path="matches[?(@.ext=='.pdf')].path", from_step=1, **extra):
    return {"tool": "steps.for_each", "arguments": {"from_step": from_step, "path": path, **MOVE, **extra}}


class SelectTests(unittest.TestCase):
    def test_paths_filters_and_wildcards(self):
        self.assertEqual(len(select(PDFS, "matches[*].path")), 3)
        self.assertEqual(select(PDFS, "$.matches[?(@.ext=='.pdf')].path"),
                         ["C:\\Users\\me\\Downloads\\a.pdf", "C:\\Users\\me\\Downloads\\b.PDF"])   # case-folded
        self.assertEqual(select(PDFS, "count"), [3])
        self.assertEqual(select(PDFS, "missing[*].path"), [])

    def test_unsupported_syntax_fails_closed(self):
        for path in ("matches[0].path", "matches..path", "matches[?(@.ext!='x')]", "a;b", ""):
            with self.assertRaises(ValueError, msg=path):
                select(PDFS, path)


class ExpandTests(unittest.TestCase):
    def setUp(self):
        self.registry = real_registry()

    def test_expansion_fills_each_item(self):
        steps, summary = expand(for_each()["arguments"], {1: PDFS}, self.registry)
        self.assertEqual([s["arguments"] for s in steps], [
            {"source": "C:\\Users\\me\\Downloads\\a.pdf", "destination": "C:\\Users\\me\\Study\\a.pdf"},
            {"source": "C:\\Users\\me\\Downloads\\b.PDF", "destination": "C:\\Users\\me\\Study\\b.PDF"}])
        self.assertEqual(summary["items"], 2)

    def test_the_limit_is_enforced(self):
        many = {"matches": [{"path": f"C:\\d\\{n}.pdf"} for n in range(80)]}
        steps, summary = expand(for_each("matches[*].path")["arguments"], {1: many}, self.registry)
        self.assertEqual(len(steps), MAX_ITEMS)
        self.assertEqual(summary["capped"], 30)
        steps, _ = expand(for_each("matches[*].path", limit=5)["arguments"], {1: many}, self.registry)
        self.assertEqual(len(steps), 5)
        with self.assertRaises(ValueError):   # above the hard cap is refused by the schema
            expand(for_each("matches[*].path", limit=51)["arguments"], {1: many}, self.registry)

    def test_messages_deletes_code_and_risky_tools_are_refused(self):
        for tool, arguments in (("message.send", {"app": "whatsapp", "to": "{item}", "text": "hi"}),
                                ("filesystem.recycle", {"path": "{item}"}),
                                ("files.organize", {"path": "{item}"}),
                                ("steps.for_each", {"from_step": 1, "path": "x", "tool": "files.open",
                                                    "arguments": {"path": "{item}"}})):
            with self.assertRaises(ValueError, msg=tool):
                expand({"from_step": 1, "path": "matches[*].path", "tool": tool, "arguments": arguments},
                       {1: PDFS}, self.registry)

    def test_bad_sources_fail_closed(self):
        with self.assertRaises(ValueError):   # no completed step 2
            expand(for_each(from_step=2)["arguments"], {1: PDFS}, self.registry)
        with self.assertRaises(ValueError):   # objects, not plain values
            expand(for_each("matches[*]")["arguments"], {1: PDFS}, self.registry)
        with self.assertRaises(ValueError):   # empty list
            expand(for_each("matches[?(@.ext=='.doc')].path")["arguments"], {1: PDFS}, self.registry)
        with self.assertRaises(ValueError):   # the arguments never use the item
            expand({"from_step": 1, "path": "matches[*].path", "tool": "files.open",
                    "arguments": {"path": "C:\\x.pdf"}}, {1: PDFS}, self.registry)

    def test_an_item_that_breaks_the_tool_contract_stops_everything(self):
        long_name = {"matches": [{"path": "C:\\" + "x" * 1200}]}
        with self.assertRaises(ValueError):
            expand(for_each("matches[*].path")["arguments"], {1: long_name}, self.registry)


class SessionTests(unittest.TestCase):
    def run_session(self, runtime, *rounds, goal="Downloads ki saari PDFs Study folder mein daal do"):
        planner = ScriptedPlanner(*rounds)
        session = AgentSession(goal, mode="owner")
        session.advance(runtime, planner)
        return session, planner

    def test_one_planning_round_moves_every_item(self):
        runtime = FakeRuntime({"files.find": PDFS})
        session, planner = self.run_session(
            runtime, continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}),
            continue_with(for_each(), finish=True, reply="Moved the PDFs."))
        moves = [c for c in runtime.calls if c[0] == "filesystem.move"]
        self.assertEqual(len(moves), 2)
        self.assertNotIn("steps.for_each", [c[0] for c in runtime.calls])   # expanded, never run as a tool
        self.assertEqual(session.status, "done")
        self.assertEqual(len(planner.seen), 2)                               # no extra round per file
        self.assertIn("[Verified: 4 of 4 steps completed.", session.reply)

    def test_one_approval_covers_exactly_the_listed_items(self):
        runtime = FakeRuntime({"files.find": PDFS}, ask={"filesystem.move"})
        session, _ = self.run_session(
            runtime, continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}),
            continue_with(for_each(), finish=True, reply="Moved."))
        self.assertEqual(session.status, "waiting_confirmation")
        card = session.snapshot()["pending"]["for_each"]
        self.assertEqual(card["count"], 2)
        self.assertEqual(card["items"][1]["source"], "C:\\Users\\me\\Downloads\\b.PDF")
        session.decide(runtime, approve=True)
        session.advance(runtime, ScriptedPlanner())
        self.assertEqual(session.status, "done")
        self.assertEqual(len(runtime.approved), 2)       # the second item was asked by the kernel, approved by the card
        self.assertEqual(session.approved_calls & {("filesystem.copy", "{}")}, set())

    def test_instructions_seen_after_the_ok_make_every_item_ask_again(self):
        runtime = FakeRuntime({"files.find": PDFS}, ask={"filesystem.move"})
        session, _ = self.run_session(
            runtime, continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}),
            continue_with(for_each(), finish=True, reply="Moved."))
        session.decide(runtime, approve=True)
        session.suspicious = True            # e.g. a file name or page tried to give instructions
        session.advance(runtime, ScriptedPlanner())
        self.assertEqual(session.status, "waiting_confirmation")   # the second item asks again
        self.assertEqual(len(runtime.approved), 1)

    def test_a_tainted_list_taints_every_item(self):
        page = {"untrusted": True, "links": [{"path": "C:\\Users\\me\\Downloads\\a.pdf"}]}
        runtime = FakeRuntime({"web.read": page})
        self.run_session(runtime, continue_with({"tool": "web.read", "arguments": {"url": "https://example.com"}}),
                         continue_with(for_each("links[*].path"), finish=True, reply="Moved."),
                         goal="move every file listed on this page (C:\\Users\\me\\Downloads\\a.pdf) into Study")
        move = [c for c in runtime.calls if c[0] == "filesystem.move"]
        self.assertEqual(len(move), 1)
        self.assertTrue(move[0][2])   # tainted, even though the path is in the goal

    def test_a_deny_stops_the_rest(self):
        runtime = FakeRuntime({"files.find": PDFS}, deny={"filesystem.move"})
        session, _ = self.run_session(
            runtime, continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}),
            continue_with(for_each(), finish=True, reply="Moved."))
        self.assertEqual(session.status, "stopped")
        self.assertEqual(len([c for c in runtime.calls if c[0] == "filesystem.move"]), 1)

    def test_a_bulk_message_is_refused_and_nothing_is_sent(self):
        runtime = FakeRuntime({"files.find": PDFS})
        bulk = {"tool": "steps.for_each", "arguments": {"from_step": 1, "path": "matches[*].path",
                                                         "tool": "message.send",
                                                         "arguments": {"app": "whatsapp", "to": "{item}",
                                                                       "text": "hello"}}}
        session, _ = self.run_session(runtime, continue_with({"tool": "files.find", "arguments": {"query": "x"}}),
                                      continue_with(bulk), goal="sabko message bhejo hello")
        self.assertNotIn("message.send", [c[0] for c in runtime.calls])
        self.assertEqual(session.steps[1]["state"], "FAILED")

    def test_a_re_planned_for_each_skips_items_already_done(self):
        runtime = FakeRuntime({"files.find": PDFS})
        session, _ = self.run_session(
            runtime, continue_with({"tool": "files.find", "arguments": {"query": "pdf"}}),
            continue_with(for_each()), continue_with(for_each(limit=50), finish=True, reply="Moved."))
        self.assertEqual(len([c for c in runtime.calls if c[0] == "filesystem.move"]), 2)


if __name__ == "__main__":
    unittest.main()

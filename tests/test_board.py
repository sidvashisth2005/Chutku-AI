"""H15: the task board, its dispatcher, and research workers that may use only the public web."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from chutku import board, research

from tests.agent_fakes import FakeRuntime, ScriptedPlanner, continue_with, real_registry


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)

    def test_a_dependency_is_promoted_only_after_its_parent_is_done(self):
        first = board.add(self.base, "python 3.14 release date", kind="research")
        second = board.add(self.base, "its new features", kind="research", parents=[first["id"]])
        self.assertEqual((first["status"], second["status"]), ("ready", "todo"))
        board.set_status(self.base, first["id"], "review")
        self.assertEqual(board.get(self.base, second["id"])["status"], "todo")
        board.set_status(self.base, first["id"], "done")
        self.assertEqual(board.get(self.base, second["id"])["status"], "ready")
        with self.assertRaises(ValueError):
            board.add(self.base, "orphan", parents=[99])

    def test_a_restart_returns_running_to_ready(self):
        task = board.add(self.base, "x", kind="research")
        board.set_status(self.base, task["id"], "running")
        self.assertEqual(board.recover(self.base), [task["id"]])
        task = board.get(self.base, task["id"])
        self.assertEqual((task["status"], task["attempts"]), ("ready", 1))

    def test_archive_never_deletes(self):
        task = board.add(self.base, "gym fees")
        board.set_status(self.base, task["id"], "archived")
        self.assertEqual(board.tasks(self.base), [])
        self.assertEqual(len(board.tasks(self.base, include_archived=True)), 1)

    def test_find_open_by_title_words(self):
        board.add(self.base, "DBMS notes banana")
        board.add(self.base, "gym fees bharna")
        self.assertEqual(board.find_open(self.base, "DBMS notes")["title"], "DBMS notes banana")
        self.assertIsNone(board.find_open(self.base, "physics assignment"))


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.notes = []
        self.clock = Clock()

    def dispatcher(self, worker, paused=lambda: False):
        dispatcher = board.Dispatcher(self.base, worker, notify=lambda t, m: self.notes.append((t, m)),
                                      paused=paused, clock=self.clock)
        self.addCleanup(dispatcher.join)   # runs before the temporary folder is removed
        return dispatcher

    def test_owner_tasks_are_never_executed(self):
        ran = []
        board.add(self.base, "DBMS notes banana")
        self.assertEqual(self.dispatcher(lambda *a: ran.append(a)).tick(), [])
        self.assertEqual(ran, [])

    def test_a_result_with_two_sources_is_done_and_saved(self):
        task = board.add(self.base, "best free pdf editor", kind="research")
        dispatcher = self.dispatcher(lambda t, beat, cancel: {"text": "PDFgear is free.",
                                                              "sources": ["https://a.example", "https://b.example"]})
        self.assertEqual(dispatcher.tick(), [task["id"]])
        self.assertTrue(wait_for(lambda: board.get(self.base, task["id"])["status"] == "done"))
        saved = Path(board.get(self.base, task["id"])["result_path"]).read_text(encoding="utf-8")
        self.assertIn("PDFgear", saved)
        self.assertIn("https://b.example", saved)
        self.assertTrue(any("best free pdf editor" in title for title, _ in self.notes))

    def test_fewer_than_two_sources_waits_for_review(self):
        task = board.add(self.base, "x", kind="research")
        dispatcher = self.dispatcher(lambda t, b, c: {"text": "maybe", "sources": ["https://a.example"]})
        dispatcher.tick()
        self.assertTrue(wait_for(lambda: board.get(self.base, task["id"])["status"] == "review"))

    def test_pause_holds_the_dispatcher(self):
        board.add(self.base, "x", kind="research")
        self.assertEqual(self.dispatcher(lambda *a: {}, paused=lambda: True).tick(), [])

    def test_concurrency_is_capped(self):
        release = threading.Event()
        for n in range(4):
            board.add(self.base, f"topic {n}", kind="research")

        def slow(task, beat, cancel):
            release.wait(5)
            return {"text": "ok", "sources": ["https://a", "https://b"]}
        dispatcher = self.dispatcher(slow)
        self.assertEqual(len(dispatcher.tick()), board.MAX_WORKERS)
        self.assertEqual(dispatcher.tick(), [])
        release.set()

    def test_a_stall_blocks_the_task(self):
        task = board.add(self.base, "x", kind="research")
        release = threading.Event()
        dispatcher = self.dispatcher(lambda t, b, cancel: (release.wait(5), {"text": "", "sources": []})[1])
        dispatcher.tick()
        self.clock.now += board.STALL_SECONDS + 1
        dispatcher.tick()
        self.assertEqual(board.get(self.base, task["id"])["status"], "blocked")
        release.set()
        time.sleep(0.1)
        self.assertEqual(board.get(self.base, task["id"])["status"], "blocked")   # the late result is ignored

    def test_failures_retry_then_block_and_the_circuit_opens(self):
        tasks = [board.add(self.base, f"t{n}", kind="research") for n in range(3)]

        def broken(task, beat, cancel):
            raise RuntimeError("web.read failed")
        dispatcher = self.dispatcher(broken)
        dispatcher.tick()
        self.assertTrue(wait_for(lambda: all(board.get(self.base, t["id"])["attempts"] >= 1 for t in tasks[:2])))
        self.assertEqual(board.get(self.base, tasks[0]["id"])["status"], "ready")   # retried later, not at once
        self.assertEqual(dispatcher.tick(), [tasks[2]["id"]])
        self.assertTrue(wait_for(lambda: board.breaker_open(self.base, self.clock.now)))
        self.clock.now += board.RETRY_SECONDS * 3
        self.assertEqual(dispatcher.tick(), [])                                    # the circuit is open
        self.assertTrue(any("paused" in title.casefold() for title, _ in self.notes))
        self.clock.now += board.BREAKER_SECONDS
        self.assertTrue(dispatcher.tick())

    def test_the_stop_button(self):
        task = board.add(self.base, "x", kind="research")
        release = threading.Event()
        dispatcher = self.dispatcher(lambda t, b, cancel: (release.wait(5), {"text": "", "sources": []})[1])
        dispatcher.tick()
        self.assertTrue(dispatcher.stop_task(task["id"]))
        self.assertEqual(board.get(self.base, task["id"])["status"], "blocked")
        release.set()


class WorkerTests(unittest.TestCase):
    def test_the_child_cannot_read_private_files_even_if_proposed(self):
        runtime = FakeRuntime({"files.find": {"matches": [{"path": "C:\\secret.pdf"}]}})
        planner = ScriptedPlanner(continue_with({"tool": "files.find", "arguments": {"query": "secret"}}))
        with self.assertRaises(RuntimeError):
            research.run_child("find my secret files and summarise them", runtime, planner)
        self.assertNotIn("files.find", [c[0] for c in runtime.calls])

    def test_the_child_menu_is_only_the_public_web(self):
        child = research.AllowlistRuntime(FakeRuntime())
        self.assertEqual({t.name for t in child.registry.list()}, set(research.PUBLIC_WEB))
        with self.assertRaises(KeyError):
            child.registry.get("task.delegate")                      # no grandchildren

    def test_a_research_run_returns_the_fetched_sources(self):
        runtime = FakeRuntime({"web.results": {"results": [{"url": "https://a.example"}]},
                               "web.read": {"text": "PDFgear is free."}})
        planner = ScriptedPlanner(
            continue_with({"tool": "web.results", "arguments": {"query": "best free pdf editor"}}),
            continue_with({"tool": "web.read", "arguments": {"url": "https://a.example"}},
                          {"tool": "web.read", "arguments": {"url": "https://b.example"}}),
            {"status": "done", "reply": "PDFgear (a.example, b.example).", "declared_plan": [], "next_steps": [],
             "finish": False})
        result = research.run_child("best free pdf editor", runtime, planner)
        self.assertEqual(result["sources"], ["https://a.example", "https://b.example"])
        self.assertIn("PDFgear", result["text"])

    def test_the_tools_and_phrases(self):
        from chutku.daily_intent import parse_daily
        with TemporaryDirectory() as temp:
            registry = real_registry()
            board.register_board_tools(registry, Path(temp))
            out = registry.get("task.delegate").execute({"goal": "release date", "then": "new features"}, None).output
            self.assertEqual([t["status"] for t in out["tasks"]], ["ready", "todo"])
            out = registry.get("board.add").execute({"title": "DBMS notes banana"}, None).output
            done = registry.get("board.done").execute({"title": "DBMS notes"}, None)
            self.assertEqual(done.output["task"]["status"], "done")
            refused = registry.get("board.done").execute({"id": 1}, None)   # a running/ready research task
            self.assertEqual(refused.verification, "FAIL")
        self.assertEqual(parse_daily("research karke batao best free PDF editor")[:2],
                         ("task.delegate", {"goal": "best free PDF editor"}))
        self.assertEqual(parse_daily("ye kaam board pe daal do: DBMS notes banana")[:2],
                         ("board.add", {"title": "DBMS notes banana"}))
        found = parse_daily("pehle meri file dhundo, phir use kholo")   # a file search, never web research
        self.assertTrue(found is None or found[0] != "task.delegate")


if __name__ == "__main__":
    unittest.main()

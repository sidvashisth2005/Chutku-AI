"""App Mastery 2, parallel lanes (owner 2026-11-10: "I do 2 tasks, Chutku does 2, in parallel"): steps in different
lanes run at the same time, steps in one lane take turns, the screen lane is still the one exclusive lock, and the
action log stays one unbroken chain when steps log at once."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from chutku.app import create_runtime
from chutku.core.action_log import ActionLog
from chutku.runtime import lane
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


class LaneNameTests(unittest.TestCase):
    def test_background_steps_get_their_own_lane(self):
        self.assertEqual(lane("desktop.do", {"app": "Notepad", "name": "File"}), "app-notepad")
        self.assertEqual(lane("apps.launch", {"name": "notepad.exe", "background": True}), "app-notepad")
        self.assertEqual(lane("browser.act", {"ref": "e2"}), "web")

    def test_everything_that_may_touch_the_screen_is_the_screen_lane(self):
        self.assertEqual(lane("apps.launch", {"name": "notepad"}), "screen")       # a normal launch comes to the front
        self.assertEqual(lane("keyboard.type_text", {"text": "hi"}), "screen")
        self.assertEqual(lane("message.send", {"to": "UB"}), "screen")
        self.assertEqual(lane("desktop.act", {"ref": "e99"}), "screen")            # unknown ref: no app known
        self.assertEqual(lane("desktop.do", {"app": "  "}), "screen")
        self.assertEqual(lane("files.move", None), "screen")


class LaneLockTests(unittest.TestCase):
    """Each task has its own runtime on its own thread, like the dashboard's side-by-side tasks."""
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.spans = []
        create_runtime(self.base).close()   # the databases exist already, as on a real install

    def tearDown(self):
        self.temp.cleanup()

    def _runtime(self, step_wait=5):
        runtime = create_runtime(self.base)
        runtime.step_wait = step_wait
        for name in ("browser.slow_test", "desktop.do", "test.slow_screen"):
            def handler(arguments, _context):
                started = time.monotonic()
                time.sleep(0.4)
                self.spans.append((arguments.get("tag"), started, time.monotonic()))
                return ToolResult({"ok": True}, Verification.PASS)
            runtime.registry._tools.pop(name, None)
            runtime.registry.register(Tool(name, "slow fake step", Risk.REVERSIBLE, handler,
                                           argument_schema={"type": "object"}))
        return runtime

    def _both(self, first, second):
        results, ready = {}, threading.Barrier(2)

        def work(index, call):
            with self._runtime() as runtime:
                ready.wait(5)
                results[index] = runtime.run(*call)
        threads = [threading.Thread(target=work, args=(i, call)) for i, call in enumerate((first, second))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        return [str(results[i]["state"]) for i in (0, 1)], results

    def _overlap(self):
        (_a, start_a, end_a), (_b, start_b, end_b) = self.spans
        return min(end_a, end_b) - max(start_a, start_b)

    def test_steps_in_different_lanes_run_at_the_same_time(self):
        states, results = self._both(("browser.slow_test", {"tag": "web"}), ("desktop.do", {"app": "Notepad", "tag": "app"}))
        self.assertEqual(states, ["COMPLETED", "COMPLETED"], results)
        self.assertGreater(self._overlap(), 0.2)

    def test_steps_in_one_lane_take_turns(self):
        states, results = self._both(("desktop.do", {"app": "Notepad", "tag": "a"}), ("desktop.do", {"app": "notepad", "tag": "b"}))
        self.assertEqual(states, ["COMPLETED", "COMPLETED"], results)
        self.assertLessEqual(self._overlap(), 0.0)

    def test_the_screen_lane_is_still_the_one_exclusive_lock(self):
        """Negative: a screen step never runs while another screen step (or a workflow holding execution_lock) does."""
        states, results = self._both(("test.slow_screen", {"tag": "a"}), ("test.slow_screen", {"tag": "b"}))
        self.assertEqual(states, ["COMPLETED", "COMPLETED"], results)
        self.assertLessEqual(self._overlap(), 0.0)
        with self._runtime() as holder, self._runtime(step_wait=0) as other:
            with holder.execution_lock:
                self.assertEqual(str(other.run("test.slow_screen", {"tag": "c"})["state"]), "FAILED")   # busy: nothing ran
                self.assertEqual(str(other.run("browser.slow_test", {"tag": "d"})["state"]), "COMPLETED")
        self.assertEqual([tag for tag, *_ in self.spans[2:]], ["d"])

    def test_an_approval_takes_the_lock_of_its_own_lane(self):
        with self._runtime() as runtime:
            token = runtime.approvals.add("task-1", "browser.slow_test", {"tag": "approved"}, runtime.granted_root)
            self.assertEqual(runtime.approvals.peek(token), ("browser.slow_test", {"tag": "approved"}))
            self.assertIs(runtime.lane_lock("browser.slow_test", {}), runtime.lane_lock("browser.other", {}))
            self.assertIs(runtime.lane_lock("files.move", {}), runtime.execution_lock)
            self.assertIsNone(runtime.approvals.peek("not-a-token"))
            runtime.approvals.take(token)   # peek did not use it up


class ActionLogUnderParallelStepsTests(unittest.TestCase):
    def test_the_chain_stays_whole_when_many_steps_log_at_once(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "data" / "actions.log.jsonl"
            logs = [ActionLog(path) for _ in range(8)]   # one per runtime, like parallel dashboard tasks

            def write(log, worker):
                for step in range(5):
                    log.append({"tool": "desktop.do", "worker": worker, "step": step})
            threads = [threading.Thread(target=write, args=(log, i)) for i, log in enumerate(logs)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(20)
            report = ActionLog(path).verify()
            self.assertTrue(report.get("ok", report.get("valid")), report)
            self.assertEqual(len(ActionLog(path)._entries()), 40)


if __name__ == "__main__":
    unittest.main()

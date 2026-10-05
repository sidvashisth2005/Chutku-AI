"""Model services: no reaping mid-request, deadlock-free GPU hand-over, cached hashes, routing (master plan S6)."""
import hashlib
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from chutku import brain_service
from chutku.agent_loop import AgentSession, is_multipart_goal, is_screen_goal
from chutku.brain_service import BrainService, claim_gpu
from chutku.core import hashcache


class FakeService:
    def __init__(self):
        self.inflight, self.closed, self.lock = 0, 0, threading.RLock()

    def close(self):
        with self.lock:
            self.closed += 1


class GpuHandoverTests(unittest.TestCase):
    def tearDown(self):
        brain_service._gpu_owner = None

    def test_the_previous_model_finishes_its_request_first(self):
        planner, vision = FakeService(), FakeService()
        claim_gpu(planner)
        planner.inflight = 1
        threading.Timer(0.3, lambda: setattr(planner, "inflight", 0)).start()
        started = time.monotonic()
        claim_gpu(vision)
        self.assertGreaterEqual(time.monotonic() - started, 0.25)   # waited for the running request
        self.assertEqual(planner.closed, 1)

    def test_two_services_starting_at_once_never_deadlock(self):
        a, b = FakeService(), FakeService()
        threads = [threading.Thread(target=claim_gpu, args=(service,)) for service in (a, b, a, b)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertFalse(any(thread.is_alive() for thread in threads))


class ReaperTests(unittest.TestCase):
    def test_never_unloads_during_a_request(self):
        service = BrainService(idle_seconds=0)
        service.last_used = time.monotonic() - 999
        service.inflight = 1
        self.assertFalse(service.idle_expired())
        service.inflight = 0
        self.assertTrue(service.idle_expired())

    def test_a_stop_during_code_generation_ends_it(self):
        service = BrainService(idle_seconds=60)
        release = threading.Event()
        closed = []
        with patch.object(service, "ensure_started"), patch.object(service, "close", lambda: closed.append(1)), \
                patch.object(BrainService, "_safe_request", staticmethod(lambda *a: (release.wait(5), (True, {}))[1])):
            def stop():
                raise InterruptedError("stopped")
            with self.assertRaises(InterruptedError):
                service.complete_text([{"role": "user", "content": "x"}], max_tokens=10, check=stop, timeout=5)
        release.set()
        self.assertEqual(closed, [1])
        self.assertEqual(service.inflight, 0)

    def test_errors_keep_the_servers_words(self):
        self.assertIn("context", brain_service._describe(ValueError("context size exceeded")))


class HashCacheTests(unittest.TestCase):
    def test_a_big_file_is_hashed_once_per_state(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "model.gguf"
        path.write_bytes(b"weights")
        expected = hashlib.sha256(b"weights").hexdigest()
        hashcache.clear()
        with patch.object(hashcache.hashlib, "file_digest", wraps=hashlib.file_digest) as digest:
            self.assertTrue(hashcache.matches(path, expected))
            self.assertTrue(hashcache.matches(path, expected))
            self.assertEqual(digest.call_count, 1)
            path.write_bytes(b"tampered")          # a changed file is hashed again and fails
            self.assertFalse(hashcache.matches(path, expected))
            self.assertEqual(digest.call_count, 2)


class StrongModelTests(unittest.TestCase):
    def test_presence_is_cheap_but_a_tampered_file_never_starts(self):
        import json
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        (base / "models").mkdir()
        (base / "models" / "big.gguf").write_bytes(b"tampered weights")
        (base / "models" / "manifest.json").write_text(json.dumps({"strong": {
            "path": "models/big.gguf", "sha256": "0" * 64}}), encoding="utf-8")
        with patch.object(hashcache.hashlib, "file_digest", wraps=hashlib.file_digest) as digest:
            service = brain_service.strong_service(base)
            self.assertIsNotNone(service)
            self.assertEqual(digest.call_count, 0)          # deciding "is there a backup?" reads nothing
            with self.assertRaises(brain_service.BrainUnavailable):
                brain_service.pinned_model(base, "strong")  # what starting it runs: the hash refuses the file
        brain_service._strong = None


class RoutingTests(unittest.TestCase):
    def test_only_real_screen_requests_go_vision_first(self):
        for goal in ("screen pe kya hai", "what is on my screen?", "ye kya hai", "click the first video",
                     "what's this error"):
            self.assertTrue(is_screen_goal(goal), goal)
        for goal in ("mind map dikhao", "ye file kholo", "open this folder D:\\Notes", "here is my list: milk"):
            self.assertFalse(is_screen_goal(goal), goal)

    def test_multipart_needs_two_steps(self):
        self.assertTrue(is_multipart_goal("Find the 5 largest files in Downloads and write their names into a file"))
        self.assertFalse(is_multipart_goal("which is bigger, 2 to the power 10 or 10 cubed? answer in one line"))

    def test_offline_the_local_planner_leads_long_tasks(self):
        class Planner:
            def __init__(self, name):
                self.name, self.calls = name, 0

            def propose(self, session, runtime, check=None):
                self.calls += 1
                return {"status": "clarify", "reply": "?", "declared_plan": [], "next_steps": []}, {"planner": self.name}

        local, backup = Planner("local"), Planner("local-8b")
        backup.cheap_second_opinion = lambda: False    # offline: the backup is the slow 8B
        session = AgentSession("Find the 5 largest files in Downloads and write their names into a file",
                               mode="owner")
        self.assertTrue(session.cloud_first)
        runtime = type("R", (), {"action_control": type("A", (), {"check": staticmethod(lambda: None)})(),
                                 "registry": None})()
        with patch("chutku.agent_loop.RuntimeRouter.wrap", return_value=type("W", (), {"default": runtime})()):
            session.advance(runtime, local, fallback=backup)
        self.assertEqual(local.calls, 1)    # the 4B was asked first
        self.assertEqual(backup.calls, 0)   # a clarify does not load the 8B offline


if __name__ == "__main__":
    unittest.main()

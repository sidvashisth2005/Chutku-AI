from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chutku.app import create_runtime
from chutku.core.resource_grants import ResourceGrantStore
from chutku.tools.registry import Risk, Tool, ToolResult, Verification


class ResourceGrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.external = self.base / "explicit external"
        self.external.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_grants_are_explicit_durable_bounded_and_revocable(self):
        path = self.base / "data/grants.db"
        store = ResourceGrantStore(path)
        sandbox = self.base / "sandbox"
        sandbox.mkdir()
        self.assertFalse(store.ensure_sandbox(sandbox).revocable)
        grant = store.grant(self.external, {"observe"})
        self.assertEqual(grant.access, {"observe"})
        store.close()
        store = ResourceGrantStore(path)
        self.assertEqual(store.get(grant.grant_id).root, self.external.resolve())
        self.assertFalse(store.revoke(grant.grant_id).active)
        with self.assertRaises(ValueError):
            store.get(grant.grant_id)
        with self.assertRaises(ValueError):
            store.revoke("sandbox")
        # Owner decision 2026-09-30: whole local drives may be granted; system areas
        # stay protected by the runtime, and modify grants inside them are refused.
        drive = store.grant(Path(self.external.anchor), {"observe"})
        self.assertEqual(drive.root, Path(self.external.anchor))
        with self.assertRaises(ValueError):
            store.grant(r"\\server\share", {"observe"})
        with self.assertRaises(ValueError):
            store.grant(Path(__import__("os").environ["SystemRoot"]), {"modify"})
        store.close()

    def test_observe_only_grant_denies_mutation_and_cannot_be_widened_by_arguments(self):
        with create_runtime(self.base) as setup:
            grant_id = setup.resource_grants.grant(self.external, {"observe"}).grant_id
        with create_runtime(self.base, grant_id) as runtime:
            self.assertEqual(runtime.run("filesystem.list", {})["state"], "COMPLETED")
            result = runtime.run("filesystem.write_text", {"path": "blocked.txt", "content": "no", "root": str(self.external)})
            self.assertEqual(result["state"], "FAILED")
            denied = runtime.run("filesystem.write_text", {"path": "blocked.txt", "content": "no"})
            self.assertEqual(denied["state"], "DENIED")
            self.assertFalse((self.external / "blocked.txt").exists())

    def test_revocation_is_rechecked_before_execution_and_approval(self):
        effects = []
        with create_runtime(self.base) as setup:
            grant_id = setup.resource_grants.grant(self.external, {"modify"}).grant_id
        runtime = create_runtime(self.base, grant_id)
        runtime.registry.register(Tool("test.external_file", "Send a fixture file.", Risk.EXTERNAL_SIDE_EFFECT,
            lambda args, ctx: (effects.append(True) or ToolResult({}, Verification.PASS)),
            resource_access="modify"))
        pending = runtime.run("test.external_file", {})
        self.assertEqual(pending["state"], "WAITING_CONFIRMATION")
        self.assertEqual(pending["approval"]["resource"]["grant_id"], grant_id)
        runtime.resource_grants.revoke(grant_id)
        with self.assertRaises(ValueError):
            runtime.approve(pending["approval"]["token"])
        self.assertFalse(effects)
        self.assertEqual(runtime.run("filesystem.list", {})["state"], "FAILED")
        runtime.close()

    def test_modify_grant_is_scoped_and_undo_uses_same_root(self):
        other = self.base / "other"
        other.mkdir()
        with create_runtime(self.base) as setup:
            first = setup.resource_grants.grant(self.external, {"modify"}).grant_id
            second = setup.resource_grants.grant(other, {"modify"}).grant_id
        with create_runtime(self.base, first) as runtime:
            self.assertEqual(runtime.run("filesystem.write_text", {"path": "one.txt", "content": "one"})["state"], "COMPLETED")
        with create_runtime(self.base, second) as runtime:
            self.assertEqual(runtime.run("filesystem.write_text", {"path": "two.txt", "content": "two"})["state"], "COMPLETED")
        with create_runtime(self.base, first) as runtime:
            self.assertEqual(runtime.run("filesystem.undo_last_write", {})["state"], "COMPLETED")
        self.assertFalse((self.external / "one.txt").exists())
        self.assertEqual((other / "two.txt").read_text(), "two")


if __name__ == "__main__":
    unittest.main()

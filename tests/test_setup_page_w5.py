"""W5: the first-run setup page: its endpoints sit behind the session token, steps persist, keys are never echoed,
and pack downloads are resumable and refused (and deleted) when their hash does not match."""
import hashlib
import http.client
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from chutku import models, setup_wizard


class Server:
    def __init__(self, base):
        from chutku.dashboard import DashboardServer
        self.server = DashboardServer(Path(base), port=0)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def call(self, method, path, body=None, token=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}", "X-Chutku-Token": token if token is not None else self.server.token}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{self.port}"})
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        data = json.loads(response.read() or b"{}")
        connection.close()
        return response.status, data

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.web = Server(self.temp.name)
        self.addCleanup(self.web.close)

    def test_every_setup_endpoint_refuses_a_bad_token(self):
        for method, body in (("GET", None), ("POST", {"action": "finish"}), ("POST", {"action": "name", "name": "x"})):
            for token in ("", "wrong-token"):
                status, _ = self.web.call(method, "/api/setup", body, token=token)
                self.assertEqual(status, 403, (method, body, token))
        self.assertFalse(setup_wizard.state(self.temp.name)["done"])        # nothing changed

    def test_steps_persist_and_finish_hides_the_page(self):
        status, view = self.web.call("GET", "/api/setup")
        self.assertEqual((status, view["done"]), (200, False))
        # the page marks this install's own start mode "(recommended)": Safe for an installed app, Full for a checkout
        from chutku.core.preferences import defaults
        self.assertEqual(view["default_mode"], defaults()["handsfree_mode"])
        self.assertEqual(view["mode"], view["default_mode"])                    # a fresh home starts on it
        self.assertEqual(set(view["packs"]), set(models.PACKS))
        self.assertEqual(self.web.call("POST", "/api/setup", {"action": "name", "name": "Asha"})[0], 200)
        self.assertEqual(self.web.call("POST", "/api/setup", {"action": "mode", "mode": "edits"})[1]["mode"],
                         "auto_edits")
        self.assertEqual(self.web.call("POST", "/api/setup", {"action": "mode", "mode": "yolo"})[0], 400)
        self.assertEqual(self.web.call("POST", "/api/setup", {"action": "rm -rf"})[0], 400)
        self.web.call("POST", "/api/setup", {"action": "finish"})
        saved = setup_wizard.state(self.temp.name)                          # independent check: the file
        self.assertTrue(saved["done"])
        self.assertIn("name", saved["steps"])
        self.assertTrue(self.web.call("GET", "/api/setup")[1]["done"])
        from chutku.mind import Mind
        self.assertEqual(Mind(Path(self.temp.name)).load()["facts"]["name"], "Asha")

    def test_a_key_is_stored_but_never_echoed(self):
        secret = "gsk_" + "A1b2C3d4" * 6
        with patch("chutku.providers.store_key") as store:
            status, view = self.web.call("POST", "/api/setup", {"action": "key", "provider": "groq", "key": secret})
        self.assertEqual(status, 200)
        store.assert_called_once_with("groq", secret)
        self.assertNotIn(secret, json.dumps(view))
        self.assertNotIn(secret, Path(self.temp.name, "data", "setup.json").read_text())


class FakeResponse(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status, self.headers = status, {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DownloadTests(unittest.TestCase):
    def test_a_wrong_hash_download_is_refused_and_deleted(self):
        with TemporaryDirectory() as temp:
            target = Path(temp) / "model.gguf"
            with self.assertRaises(OSError):
                models.download("https://x/model.gguf", target, "0" * 64, opener=lambda r, timeout: FakeResponse(b"evil"))
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])                 # no partial left either

    def test_a_partial_download_resumes_with_a_range_request(self):
        whole = b"0123456789" * 1000
        with TemporaryDirectory() as temp:
            target = Path(temp) / "m.bin"
            target.with_suffix(".bin.download").write_bytes(whole[:4000])
            seen, progress = [], []

            def opener(request, timeout):
                seen.append(request.get_header("Range"))
                return FakeResponse(whole[4000:], status=206)
            models.download("https://x/m.bin", target, hashlib.sha256(whole).hexdigest(),
                            progress=lambda done, total: progress.append((done, total)), opener=opener)
            self.assertEqual(seen, ["bytes=4000-"])
            self.assertEqual(target.read_bytes(), whole)
            self.assertEqual(progress[-1], (10000, 10000))

    def test_a_pack_installs_only_its_own_files(self):
        data = {"stt": {"directory": "models/whisper", "source": "https://huggingface.co/x/y", "revision": "r"},
                "tts": {"model": {"source": "https://x/k.onnx", "path": "models/kokoro/k.onnx", "sha256": "a" * 64},
                        "voices": {"source": "https://x/v.bin", "path": "models/kokoro/v.bin", "sha256": "b" * 64}}}
        with TemporaryDirectory() as temp:
            fetched, snapshots = [], []

            def fetcher(url, path, expected, progress=None):
                fetched.append(Path(path).name)
                Path(path).write_bytes(b"x")

            def snapshot(base, label, entry):
                snapshots.append(label)
                (Path(base) / entry["directory"]).mkdir(parents=True)
            self.assertTrue(models.install_pack(temp, "voice", data=data, fetcher=fetcher, snapshot=snapshot))
            self.assertEqual((sorted(fetched), snapshots), (["k.onnx", "v.bin"], ["stt"]))
            self.assertTrue(models.pack_installed(temp, "voice", data))
            self.assertFalse(models.pack_installed(temp, "screen", {"vision": {"model": {
                "source": "s", "path": "models/vl.gguf", "sha256": "c" * 64}}}))
        with self.assertRaises(ValueError):
            models.install_pack("/tmp", "everything", data=data)

    def test_a_path_outside_models_is_refused(self):
        with TemporaryDirectory() as temp:
            data = {"tts": {"model": {"source": "s", "path": "../evil.exe", "sha256": "a" * 64}}}
            with self.assertRaises(OSError):
                models.install_pack(temp, "voice", data=data, fetcher=lambda *a, **k: None, snapshot=lambda *a: None)

    def test_the_background_job_reports_a_failure(self):
        with TemporaryDirectory() as temp:
            jobs = models.Downloads(temp)

            def broken(base, pack, progress):
                progress("tts.model", 10, 100)
                raise OSError("k.onnx: downloaded file does not match its pinned hash (deleted).")
            jobs.start("voice", installer=broken)
            for _ in range(100):
                if jobs.status()["voice"]["state"] != "downloading":
                    break
                threading.Event().wait(0.02)
            status = jobs.status()["voice"]
            self.assertEqual(status["state"], "failed")
            self.assertIn("does not match", status["error"])


class CliStillWorksTests(unittest.TestCase):
    def test_the_cli_marks_setup_done(self):
        with TemporaryDirectory() as temp:
            answers = iter(["", "", "", "n", "2"])   # then Enter for every later question
            setup_wizard.run(Path(temp), ask=lambda _q: next(answers, ""), secret=lambda _q: "", out=lambda *_: None)
            self.assertTrue(setup_wizard.state(temp)["done"])


if __name__ == "__main__":
    unittest.main()

"""Offline mode: local models first, Gemini only as the backup (owner, 2026-10-04)."""
import types
import unittest
from unittest.mock import patch

import numpy as np

from chutku import brain_service, online, vision
from chutku.cloud_planner import BackupPlanner


class Planner:
    def __init__(self, name, error=None):
        self.name, self.error, self.calls = name, error, 0

    def propose(self, session, runtime, check=None):
        self.calls += 1
        if self.error:
            raise self.error
        return {"status": "done"}, {"planner": self.name}


class BackupChainTests(unittest.TestCase):
    def chain(self, gemini, online_now, strong=True):
        chain = BackupPlanner(gemini, object() if strong else None, online=lambda: online_now)
        self.local = Planner("local-8b")
        chain._strong = lambda: self.local
        return chain

    def test_online_uses_gemini(self):
        gemini = Planner("gemini")
        _, meta = self.chain(gemini, True).propose(None, None)
        self.assertEqual((meta["planner"], self.local.calls), ("gemini", 0))

    def test_offline_skips_gemini_and_uses_the_local_8b(self):
        gemini = Planner("gemini")
        chain = self.chain(gemini, False)
        _, meta = chain.propose(None, None)
        self.assertEqual((meta["planner"], gemini.calls, chain.name), ("local-8b", 0, "local-8b"))

    def test_gemini_failing_mid_request_falls_back(self):
        gemini = Planner("gemini", OSError("503"))
        _, meta = self.chain(gemini, True).propose(None, None)
        self.assertEqual(meta["planner"], "local-8b")

    def test_second_opinion_is_cheap_only_with_gemini_online(self):
        self.assertTrue(self.chain(Planner("gemini"), True).cheap_second_opinion())
        self.assertFalse(self.chain(Planner("gemini"), False).cheap_second_opinion())
        self.assertFalse(self.chain(None, True).cheap_second_opinion())

    def test_nothing_available_fails_closed(self):
        with self.assertRaises(OSError):
            self.chain(None, False, strong=False).propose(None, None)
        with self.assertRaises(OSError):
            self.chain(Planner("gemini", OSError("down")), True, strong=False).propose(None, None)


class CoderChoiceTests(unittest.TestCase):
    def test_offline_builds_with_the_local_8b(self):
        from chutku.tools import builder
        strong = types.SimpleNamespace(variant="strong")
        with patch("chutku.tools.builder.gemini_allowed", return_value="key"), \
                patch("chutku.online.reachable", return_value=False), \
                patch("chutku.brain_service.strong_service", return_value=strong):
            coder, note = builder.choose_coder("auto")
        self.assertEqual((coder.name, coder.model), ("local", "Qwen3-8B (local)"))
        with patch("chutku.tools.builder.gemini_allowed", return_value="key"), \
                patch("chutku.online.reachable", return_value=True):
            self.assertEqual(builder.choose_coder("auto")[0].name, "gemini")


def shot():
    return vision.Shot(np.zeros((100, 200, 3), np.uint8), 0, 0, 200, 100, {"title": "App", "executable": "a.exe"})


class LocalSeeingTests(unittest.TestCase):
    def test_local_answer_boxes_and_ocr_text_elements(self):
        answer = ('{"summary":"Notepad","answer":"","elements":[{"label":"File","kind":"menu",'
                  '"bbox_2d":[0,0,100,100]},{"label":"bad","kind":"x","bbox_2d":[9,9,1,1]}]}')
        look = lambda *a, **k: (answer, {"model": "local:Qwen3-VL-4B", "backend": "Vulkan"})
        ocr = lambda s, r: [{"text": "File", "rect": (0, 0, 20, 10)}, {"text": "Save as", "rect": (50, 50, 90, 60)}]
        seen = vision.see(shot(), "", None, look=look, ocr=ocr)
        self.assertEqual([(e["id"], e["label"]) for e in seen["elements"]], [("e1", "File"), ("e2", "Save as")])
        self.assertEqual(seen["elements"][0]["rect"], (0, 0, 20, 10))   # x1,y1,x2,y2 in 0-1000 -> pixels
        self.assertTrue(seen["local"])

    def test_gemini_is_only_the_backup_and_only_online_with_a_key(self):
        def broken(*a, **k):
            raise OSError("vision model missing")
        with patch.object(vision, "see_gemini", return_value={"elements": []}) as gemini, \
                patch("chutku.online.reachable", return_value=True):
            seen = vision.see(shot(), "", "key", look=broken, ocr=lambda *a: [])
        gemini.assert_called_once()
        self.assertIn("Gemini was used", seen["note"])
        with patch.object(vision, "see_gemini") as gemini, patch("chutku.online.reachable", return_value=False):
            with self.assertRaises(OSError):
                vision.see(shot(), "", "key", look=broken, ocr=lambda *a: [])
            with self.assertRaises(OSError):
                vision.see(shot(), "", None, look=broken, ocr=lambda *a: [])
        gemini.assert_not_called()


class GpuShareTests(unittest.TestCase):
    def test_starting_one_local_model_unloads_the_other(self):
        closed = []
        a = types.SimpleNamespace(close=lambda: closed.append("a"))
        b = types.SimpleNamespace(close=lambda: closed.append("b"))
        brain_service.claim_gpu(a)
        brain_service.claim_gpu(a)
        brain_service.claim_gpu(b)
        self.assertEqual(closed, ["a"])
        brain_service.claim_gpu(None)


class OnlineCheckTests(unittest.TestCase):
    def test_unreachable_host_is_reported_offline_and_cached(self):
        online.forget()
        with patch("socket.create_connection", side_effect=OSError("no route")) as connect:
            self.assertFalse(online.reachable("example.invalid", now=100.0))
            self.assertFalse(online.reachable("example.invalid", now=110.0))
        self.assertEqual(connect.call_count, 1)
        online.forget()


class OfflineSwitchTests(unittest.TestCase):
    def test_offline_mode_blocks_every_gemini_call(self):
        from chutku import gemini
        with patch.dict("os.environ", {"CHUTKU_OFFLINE": "1"}), \
                patch("urllib.request.urlopen", side_effect=AssertionError("network used")):
            self.assertFalse(online.reachable())
            with self.assertRaises(gemini.GeminiUnavailable):
                gemini.generate("k" * 30, "gemini-x", "sys", "hi")

    def test_switch_phrases(self):
        from chutku.quick_intents import quick_proposal
        for text, on in (("offline mode on", True), ("go offline", True), ("offline mode band karo", False),
                         ("go online", False)):
            step = quick_proposal(text)["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("settings.offline_mode", {"on": on}), text)
        self.assertIsNone(quick_proposal("is my internet offline"))


class LocalConversationTests(unittest.TestCase):
    def test_end_words(self):
        from chutku.dashboard import DashboardServer
        for text in ("bas", "Bye.", "thank you", "that's all", "kuch nahi"):
            self.assertTrue(DashboardServer.END_CONVERSATION.fullmatch(text), text)
        for text in ("bas ek kaam aur karo", "volume badhao"):
            self.assertFalse(DashboardServer.END_CONVERSATION.fullmatch(text), text)

    def test_offline_live_conversation_is_not_attempted(self):
        from chutku.dashboard import DashboardServer
        server = types.SimpleNamespace(base=".", wake=None)
        with patch("chutku.tools.builder.gemini_allowed", return_value="key"), \
                patch("chutku.online.reachable", return_value=False), \
                patch("chutku.voice.live.LiveConversation", side_effect=AssertionError("must not connect")):
            self.assertFalse(DashboardServer.start_live(server))


if __name__ == "__main__":
    unittest.main()

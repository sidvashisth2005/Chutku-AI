import unittest

from chutku.quick_intents import quick_proposal
from chutku.tools import audio_output

DEVICES = [{"name": "Speakers (Realtek(R) Audio)", "id": "a", "default": True},
           {"name": "Headphones (WH-1000XM4 Stereo)", "id": "b", "default": False},
           {"name": "LG TV (NVIDIA High Definition Audio)", "id": "c", "default": False}]


class AudioOutputTests(unittest.TestCase):
    def test_match_by_words_and_aliases(self):
        self.assertEqual(audio_output.match(DEVICES, "headphones")["id"], "b")
        self.assertEqual(audio_output.match(DEVICES, "my speakers")["id"], "a")
        self.assertEqual(audio_output.match(DEVICES, "TV")["id"], "c")
        self.assertEqual(audio_output.match(DEVICES, "wh-1000xm4")["id"], "b")
        with self.assertRaises(ValueError) as unknown:
            audio_output.match(DEVICES, "bluetooth car")
        self.assertIn("Available: Speakers", str(unknown.exception))
        with self.assertRaises(ValueError):
            audio_output.match(DEVICES + [{"name": "Speakers (USB)", "id": "d", "default": False}], "speakers")

    def test_phrases(self):
        for text, device in (("switch audio to headphones", "headphones"), ("use my speakers", "speakers"),
                             ("headphones pe sound karo", "headphones"), ("change the sound output to TV", "TV")):
            step = quick_proposal(text, apps=[])["next_steps"][0]
            self.assertEqual((step["tool"], step["arguments"]), ("audio.set_output", {"device": device}), text)
        self.assertEqual(quick_proposal("list audio devices", apps=[])["next_steps"][0]["tool"], "audio.outputs")

    def test_unknown_device_is_reported_without_the_model(self):
        import tempfile
        from pathlib import Path
        from chutku.agent_loop import AgentSession, RuntimeRouter, default_context
        from chutku.app import create_runtime
        from chutku.quick_intents import QuickPlanner

        class NoModel:
            name = "local"

            def propose(self, *args, **kwargs):
                raise AssertionError("the model planner must not be needed")

        with tempfile.TemporaryDirectory() as temp, create_runtime(Path(temp)) as runtime:
            runtime.capability_grants.grant("audio.modify")
            router = RuntimeRouter(runtime)
            try:
                session = AgentSession("switch audio to bluetooth car", mode="auto_safe", context=default_context(router))
                session.quick = QuickPlanner()
                snapshot = session.advance(router, NoModel())
            finally:
                router.close()
        self.assertEqual(snapshot["status"], "clarify")
        self.assertIn("No playback device matches", snapshot["reply"])

    def test_real_devices_and_policy_interface(self):
        devices = audio_output.outputs()
        self.assertTrue(devices)
        self.assertEqual(sum(d["default"] for d in devices), 1)
        current = next(d for d in devices if d["default"])
        audio_output.set_default(current["id"])  # re-select the device already in use: exercises IPolicyConfig harmlessly
        self.assertEqual(next(d for d in audio_output.outputs() if d["default"])["id"], current["id"])


if __name__ == "__main__":
    unittest.main()

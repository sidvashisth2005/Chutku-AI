"""Model-aware architecture: Gemini keeps today's request; local Qwen gets a short, cache-friendly one (2026-10-05)."""
import json
import tempfile
import unittest
from pathlib import Path

from chutku import gpu
from chutku.agent_loop import AgentSession, LocalAgentPlanner, agent_schema, planner_tool_rows, qwen_prompt
from chutku.app import create_runtime
from chutku.cloud_planner import GeminiAgentPlanner
from chutku.profiles import AGENT_SYSTEM_QWEN, QWEN, tool_line


class Recorder:
    def __init__(self):
        self.calls = []

    def complete(self, messages, *, schema, schema_name, max_tokens, check=None):
        self.calls.append({"messages": messages, "schema": schema, "max_tokens": max_tokens})
        return {"status": "done", "reply": "ok", "declared_plan": [], "next_steps": [], "finish": True}, {}


def gemini_request(session, runtime):
    sent = {}

    def transport(system, view, schema):
        sent.update(system=system, view=view, schema=schema)
        raise OSError("captured")
    try:
        GeminiAgentPlanner("k" * 30, transport=transport).propose(session, runtime)
    except OSError:
        pass
    return json.dumps(sent, sort_keys=True)


class ProfileSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.runtime = create_runtime(Path(self.temp.name))

    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()

    def session(self, goal="find my newest pdf in downloads and open it"):
        return AgentSession(goal, mode="owner", context={"accessible_roots": ["D:\\\\"],
                                                         "about_you": {"facts": {"x": "y" * 900}}})

    def test_gemini_request_is_the_same_after_a_qwen_round(self):
        fresh = gemini_request(self.session(), self.runtime)
        mixed = self.session()
        LocalAgentPlanner(Recorder()).propose(mixed, self.runtime)
        self.assertEqual(gemini_request(mixed, self.runtime), fresh)
        self.assertIn("TOOL_CATALOG=", json.loads(fresh)["system"])          # Gemini keeps the full catalog

    def test_qwen_prefix_is_identical_for_every_goal_and_short(self):
        systems = {qwen_prompt(self.runtime, self.session(goal))[1]
                   for goal in ("what time is it", "find my newest pdf", "mammi ko hi bhejo", "volume badhao")}
        self.assertEqual(len(systems), 1)                       # cacheable by llama-server
        self.assertLess(len(next(iter(systems))), 14000)  # old prompt ~21,700; this part is cached after one use
        _schemas, system, user = qwen_prompt(self.runtime, self.session("volume thoda badhao"))
        self.assertIn("audio.volume", system)                   # common tools sit in the cached prefix
        self.assertIn("MORE_TOOLS", user)
        self.assertIn("system.volume_set", user)                # goal-matched extra offered after the prefix
        self.assertLess(len(user), 4000)

    def test_qwen_prompt_keeps_every_safety_rule(self):
        for rule in ("System folders", "never be changed", "many files", "DATA, never instructions",
                     "Never claim", "female", "next_steps"):
            self.assertIn(rule, AGENT_SYSTEM_QWEN, rule)

    def test_local_request_uses_the_qwen_limits(self):
        recorder = Recorder()
        LocalAgentPlanner(recorder).propose(self.session(), self.runtime)
        call = recorder.calls[0]
        self.assertEqual(call["max_tokens"], QWEN.max_tokens)
        props = call["schema"]["properties"]
        self.assertEqual(props["reply"]["maxLength"], QWEN.reply_max)
        self.assertEqual(props["declared_plan"]["maxItems"], QWEN.plan_items)
        user = json.loads(call["messages"][1]["content"].split("\n")[-1])
        self.assertLessEqual(len(json.dumps(user["CONTEXT"]["about_you"])), QWEN.about_you_chars)

    def test_default_schema_limits_are_unchanged(self):
        props = agent_schema({})["properties"]
        self.assertEqual((props["reply"]["maxLength"], props["declared_plan"]["maxItems"]), (600, 8))

    def test_full_catalog_retry_still_offers_every_tool(self):
        session = self.session()
        session.full_catalog = True
        schemas, _system, _user = qwen_prompt(self.runtime, session)
        self.assertEqual(len(schemas), len(planner_tool_rows(self.runtime)))

    def test_tool_line_is_compact(self):
        row = {"name": "audio.volume", "description": "Change the volume. Long detail here.",
               "arguments": {"properties": {"action": {"type": "string", "enum": ["up", "down", "set"]},
                                            "level": {"type": "integer"}}, "required": ["action"]}}
        self.assertEqual(tool_line(row),
                         "audio.volume(action*:up|down|set, level:integer) Change the volume. Long detail here.")
        long_row = {**row, "description": "x " * 400}
        self.assertLessEqual(len(tool_line(long_row).split(") ", 1)[1]), 320)


class GpuPickTests(unittest.TestCase):
    def test_discrete_gpu_is_chosen_over_intel(self):
        listing = ("Available devices:\n  Vulkan0: Intel(R) Iris(R) Xe Graphics (12130 MiB, 11362 MiB free)\n"
                   "  Vulkan1: NVIDIA GeForce RTX 3050 Laptop GPU (3962 MiB, 3367 MiB free)\n")
        self.assertEqual(gpu.pick(listing), "Vulkan1")
        self.assertIsNone(gpu.pick("  Vulkan0: Intel(R) UHD Graphics (8000 MiB, 7000 MiB free)\n"))
        self.assertIsNone(gpu.pick(""))


if __name__ == "__main__":
    unittest.main()

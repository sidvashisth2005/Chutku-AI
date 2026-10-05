"""How fast is the local planner on this PC? Replays Chutku's real planner requests (built by the current code) against
a llama-server and reports prompt / cache / generation speed per goal.

Usage: .venv\\Scripts\\python.exe scripts\\bench_local_speed.py [--model models\\X.gguf] [--draft models\\Y.gguf]
       [--old-prompt] [--repeat 2]
--old-prompt sends the pre-2026-10-05 full prompt (Gemini-style catalog) for comparison.
Stop the running Chutku's model first (or expect GPU contention). Results also depend on power: on battery this
laptop's GPU runs ~4x slower (measured 2026-10-05).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.agent_loop import (AGENT_SYSTEM, AgentSession, LocalAgentPlanner, RuntimeRouter, agent_schema,  # noqa: E402
                               default_context, planner_catalog)
from chutku.app import create_runtime  # noqa: E402
from chutku.gpu import discrete_device  # noqa: E402

GOALS = ["which is bigger, 2 to the power 10 or 10 cubed?", "find my newest pdf in downloads and open it",
         "mere desktop pe kitni files hain", "What's the weather in Delhi right now?"]
# The weather goal is replayed as its second round: web.weather already ran (a sample result below), so the model
# only has to answer from the observation (the round that was slow in the 45-task benchmark).
WEATHER_STEP = {"tool": "web.weather", "arguments": {"place": "Delhi"}, "state": "COMPLETED", "purpose": "weather",
                "observation": {"place": "Delhi, India", "now": {"temperature_c": 31.4, "feels_like_c": 34.0,
                                "sky": "Partly cloudy", "humidity_percent": 58, "wind_kmh": 9},
                                "today": {"min_c": 24.1, "max_c": 33.2, "rain_chance_percent": 10},
                                "next_days": [{"day": f"2026-10-0{d}", "min_c": 23 + d / 10, "max_c": 32 + d / 10,
                                               "sky": "Sunny"} for d in range(6, 10)]}}
EXE = ROOT / "vendor/llama-b11181-vulkan/llama-server.exe"
PORT = 18451


class Recorder:
    def __init__(self):
        self.calls = []

    def complete(self, messages, *, schema, schema_name, max_tokens, check=None):
        self.calls.append({"messages": messages, "schema": schema, "max_tokens": max_tokens})
        raise OSError("captured")


def requests(old_prompt):
    out = []
    with create_runtime(ROOT) as runtime:
        context = default_context(RuntimeRouter(runtime, opener=lambda _g: None))
        for goal in GOALS:
            session = AgentSession(goal, mode="owner", context=context)
            if "weather" in goal:
                session.steps.append(dict(WEATHER_STEP))
            if old_prompt:
                schemas, catalog = planner_catalog(runtime, session)
                out.append({"messages": [{"role": "system", "content": AGENT_SYSTEM + "TOOL_CATALOG=" + catalog},
                                         {"role": "user", "content": session.planner_input()}],
                            "schema": agent_schema(schemas), "max_tokens": 700})
                continue
            recorder = Recorder()
            try:
                LocalAgentPlanner(recorder).propose(session, runtime)
            except OSError:
                pass
            out.append(recorder.calls[0])
    return out


def call(payload):
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                     data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(request, timeout=900).read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="models/Qwen3-4B-Q4_K_M.gguf")
    parser.add_argument("--draft")
    parser.add_argument("--old-prompt", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--ctx", default="16384")
    parser.add_argument("--draft-gpu-layers", default="99")
    parser.add_argument("--kv-ram", action="store_true", help="keep the KV cache in system RAM (frees GPU memory)")
    args = parser.parse_args()
    device = discrete_device(str(EXE))
    command = [str(EXE), "--model", str(ROOT / args.model), "--host", "127.0.0.1", "--port", str(PORT), "--offline",
               "--no-webui", "--ctx-size", args.ctx, "--parallel", "1", "--reasoning", "off", "--n-gpu-layers", "99",
               "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]
    if device:
        command += ["--device", device]
    if args.kv_ram:
        command += ["--no-kv-offload"]
    if args.draft:
        command += ["--model-draft", str(ROOT / args.draft), "--gpu-layers-draft", args.draft_gpu_layers, "--spec-draft-n-max", "16",
                    "--cache-type-k-draft", "q8_0", "--cache-type-v-draft", "q8_0",
                    "--spec-draft-n-min", "1"] + (["--device-draft", device] if device and args.draft_gpu_layers != "0" else [])
    reqs = requests(args.old_prompt)
    server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        started = time.monotonic()
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
                break
            except OSError:
                if server.poll() is not None or time.monotonic() - started > 180:
                    raise SystemExit("server did not start (out of graphics memory?)")
                time.sleep(0.3)
        print(f"model={args.model} draft={args.draft} ctx={args.ctx} draft_ngl={args.draft_gpu_layers} device={device} old_prompt={args.old_prompt} "
              f"startup={time.monotonic() - started:.1f}s")
        walls = []
        for index, r in enumerate(reqs):
            for attempt in range(args.repeat):
                payload = {"messages": r["messages"], "temperature": 0, "seed": 42, "max_tokens": r["max_tokens"],
                           "response_format": {"type": "json_schema", "json_schema": {"name": "agent_step",
                                                                                     "strict": True,
                                                                                     "schema": r["schema"]}}}
                t = time.monotonic()
                out = call(payload)
                wall = time.monotonic() - t
                walls.append(wall)
                tm = out.get("timings", {})
                print(f"  goal{index} run{attempt}: {wall:5.1f}s | new prompt {tm.get('prompt_n')} tok "
                      f"{tm.get('prompt_ms', 0) / 1000:4.1f}s | gen {tm.get('predicted_n')} tok "
                      f"{tm.get('predicted_per_second', 0):.1f}/s"
                      + (f" | draft {tm.get('draft_n_accepted')}/{tm.get('draft_n')}" if tm.get("draft_n") else "")
                      + f" | {out['choices'][0]['message']['content'][:70]!r}", flush=True)
        print(f"median {sorted(walls)[len(walls) // 2]:.1f}s")
    finally:
        server.kill()


if __name__ == "__main__":
    main()

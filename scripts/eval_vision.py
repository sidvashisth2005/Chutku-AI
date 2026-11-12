r"""Local eyes check: the same screenshot questions to a vision model + projector, scored against known answers.

The picture is synthetic (a music library and a chat list drawn with known names), so nothing private is captured.
Usage: .venv\Scripts\python.exe scripts\eval_vision.py --image X.png --model M.gguf --mmproj P.gguf
       [--exe vendor\...\llama-server.exe] [--ngl auto] [--extra "--image-min-tokens 1024"]
Stop the running Chutku's models first (one 4 GB GPU).
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from chutku.gpu import discrete_device  # noqa: E402

PORT = 18481
QUESTIONS = [  # (question, words the right answer must contain, case-insensitive)
    ("Which playlist is just below After Party?", ["lo-fi"]),
    ("Kis chat mein sabse zyada unread messages hain?", ["rohan"]),
    ("Mammi ne last message mein kya likha?", ["khana"]),
    ("What time is shown next to KitKat?", ["8:15"]),
    ("Arijit Singh Mix ke upar wali playlist ka naam batao.", ["lo-fi"]),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mmproj", required=True)
    parser.add_argument("--exe", default="vendor/llama-b11181-vulkan/llama-server.exe")
    parser.add_argument("--ngl", default="99")
    parser.add_argument("--extra", default="")
    args = parser.parse_args()
    command = [str(ROOT / args.exe), "--model", str(ROOT / args.model), "--mmproj", str(ROOT / args.mmproj),
               "--host", "127.0.0.1", "--port", str(PORT), "--offline", "--no-webui", "--ctx-size", "8192",
               "--parallel", "1", "--reasoning", "off", "--n-gpu-layers", args.ngl,
               "--flash-attn", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"] + args.extra.split()
    device = discrete_device(command[0])   # same card choice as chutku/local_vision.py
    command += ["--device", device] if device else []
    image = "data:image/png;base64," + base64.b64encode(Path(args.image).read_bytes()).decode()
    started = time.monotonic()
    server = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    right = 0
    try:
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
                break
            except OSError:
                if server.poll() is not None or time.monotonic() - started > 300:
                    raise SystemExit("server did not start")
                time.sleep(0.3)
        print(f"server ready in {time.monotonic() - started:.1f}s", flush=True)
        for question, words in QUESTIONS:
            payload = {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}},
                                                                 {"type": "text", "text": question + " Answer in one short line."}]}],
                       "temperature": 0, "seed": 42, "max_tokens": 60}
            request = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=json.dumps(payload).encode(),
                                             headers={"Content-Type": "application/json"})
            t = time.monotonic()
            try:
                answer = json.loads(urllib.request.urlopen(request, timeout=600).read())["choices"][0]["message"]["content"]
            except OSError as error:
                answer = f"error {error}"
            ok = all(w in answer.casefold() for w in words)
            right += ok
            print(f"{'PASS' if ok else 'MISS'} {time.monotonic() - t:5.1f}s {question} -> {answer.strip()[:90]!r}", flush=True)
    finally:
        peak = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Process -Id {server.pid}).PeakWorkingSet64"],
                              capture_output=True, text=True).stdout.strip()
        print(f"server peak working set {int(peak or 0) / 2**30:.2f} GB", flush=True)
        server.kill()
    print(f"model={args.model}: {right}/{len(QUESTIONS)} right")


if __name__ == "__main__":
    main()

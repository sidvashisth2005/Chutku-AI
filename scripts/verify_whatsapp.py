"""Dry run of the WhatsApp named-chat path on the owner's PC: never types or sends a message.

Usage: .venv\\Scripts\\python.exe scripts\\verify_whatsapp.py --chat "AK"
Searches the chat, clicks the exact match, confirms the header shows the name, then presses Esc.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chutku.tools.apps_extra import _send_to_named_chat  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", required=True, help="Exact WhatsApp chat name")
    args = parser.parse_args()
    started = time.monotonic()
    result = _send_to_named_chat(args.chat, "(dry run: never typed)", dry_run=True)
    print(json.dumps({"verification": str(result.verification), "seconds": round(time.monotonic() - started, 1),
                      "output": result.output}, ensure_ascii=False, indent=1))
    return 0 if str(result.verification) == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Runs one approved Chutku skill (chutku/skills.py): ``python -I -B -X utf8 skill_runner.py <skill folder>``.

The arguments arrive as JSON on stdin; the skill's run(args) result goes to stdout as one JSON object. Anything the
skill prints itself goes to stderr so it cannot pose as the result. Standard library only: it runs isolated (-I).
"""
import contextlib
import importlib.util
import json
from pathlib import Path
import sys


def main():
    folder = Path(sys.argv[1])
    arguments = json.loads(sys.stdin.read() or "{}")
    spec = importlib.util.spec_from_file_location("tool", folder / "tool.py")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(sys.stderr):
        spec.loader.exec_module(module)
        result = module.run(arguments)
    if not isinstance(result, dict):
        raise TypeError(f"run() returned {type(result).__name__}, not a dict")
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()

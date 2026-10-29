"""Atlas actions as Chutku tools (App Mastery A1): every action of every valid atlas becomes `app.<app>.<id>`.

Risk comes from the action's class (safe R1, changes R2, consequential R3, destructive R4 + deletes, so it always
asks). The kernel, the owner's never-rules, taint rules, the reliability ledger and the action log therefore apply to
app actions exactly as to every other tool.
"""
from __future__ import annotations

import re

from chutku.apps import atlas as atlas_module
from chutku.apps import runner
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

DRIVER = None   # tests set a fake Driver here; None means the real one
# A "path" parameter goes to the app's own command line: a full Windows path, never a "-flag", no shell characters.
_PATH = re.compile(r"[A-Za-z]:\\[^<>\"|?*&^%!\x00-\x1f]{0,250}")


def _make(app_atlas, action):
    schema = atlas_module.param_schema(action)
    kinds = {name: (spec or {}).get("type", "text") for name, spec in (action.get("params") or {}).items()}

    def validate(arguments):
        if not isinstance(arguments, dict) or set(arguments) != set(schema["properties"]):
            raise ValueError(f"Give exactly: {', '.join(schema['properties']) or 'no arguments'}.")
        for name, spec in schema["properties"].items():
            value = arguments[name]
            if spec["type"] == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise ValueError(f"{name} must be a number")
            if spec["type"] == "string" and (not isinstance(value, str) or not 0 < len(value.strip()) <= 300):
                raise ValueError(f"{name} must be 1-300 characters")
            if kinds.get(name) == "path" and not _PATH.fullmatch(value):
                # Paths go to the app's own command line: a full Windows path only, never a "-flag".
                raise ValueError(f"{name} must be a full path like D:\\Folder\\file.txt")

    def execute(arguments, _context):
        result = runner.run(app_atlas, action, arguments, DRIVER)
        if result.get("ok") and isinstance(arguments.get("name"), str):
            try:   # a playlist/artist/album that really played is remembered for loose sentences later (F6)
                from chutku.apps import known
                known.remember(app_atlas["app"], action["id"], arguments["name"], base=_context.granted_root.parent)
            except (OSError, AttributeError):
                pass
        return ToolResult(result, Verification.PASS if result.get("ok") else Verification.FAIL)

    risk = atlas_module.RISK[action["risk"]]
    return Tool(f"app.{app_atlas['app']}.{action['id']}",
                f"{app_atlas.get('name', app_atlas['app'])}: {action['title']}", Risk(risk), execute, validate,
                argument_schema=schema, required_capability="desktop.input", reversibility="compensatable" if action["risk"] in {"safe", "changes"} else
                "none", success_predicate="atlas_check_passed", deletes=action["risk"] == "destructive")


def _howto_tool(atlases):
    from chutku.apps import howto
    apps = sorted(p.stem for p in howto.MAPS.glob("*.md") if p.stem != "README")

    def validate(arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"app", "question"}:
            raise ValueError("Give app and question.")
        if arguments["app"] not in apps:
            raise ValueError(f"app must be one of {', '.join(apps)}")
        if not isinstance(arguments["question"], str) or not 0 < len(arguments["question"].strip()) <= 300:
            raise ValueError("question must be 1-300 characters")

    def execute(arguments, _context):
        from chutku.app import PROJECT_ROOT
        from chutku.apps.lab import verified_actions
        app = arguments["app"]
        out = howto.answer(arguments["question"], app, atlases.get(app), verified_actions(PROJECT_ROOT).get(app, set()))
        found = bool(out["answers"] or out["can_do"])
        return ToolResult(out, Verification.PASS if found else Verification.FAIL)

    return Tool("apps.howto", "How to do something in one of the owner's daily apps (from its feature map), and "
                "whether Chutku can do it herself", Risk.OBSERVATION, execute, validate,
                argument_schema={"type": "object", "properties": {
                    "app": {"type": "string", "enum": apps},
                    "question": {"type": "string", "minLength": 1, "maxLength": 300}},
                    "required": ["app", "question"], "additionalProperties": False},
                success_predicate="answer_found")


def register_app_tools(registry, directory=None):
    """Register every valid atlas's actions and apps.howto; returns {"apps", "actions", "refused": {file: error}}."""
    atlases, errors = atlas_module.load_all(directory) if directory else atlas_module.load_all()
    registry.register(_howto_tool(atlases))
    from chutku.apps import extras
    extras.register(registry)
    count = 0
    for app_atlas in atlases.values():
        for action in app_atlas["actions"]:
            registry.register(_make(app_atlas, action))
            count += 1
    if errors:
        from chutku.core.log import get_logger
        for name, error in errors.items():
            get_logger("apps").warning("atlas %s refused: %s", name, error)
    return {"apps": len(atlases), "actions": count, "refused": errors}

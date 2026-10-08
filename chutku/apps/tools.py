"""Atlas actions as Chutku tools (App Mastery A1): every action of every valid atlas becomes `app.<app>.<id>`.

Risk comes from the action's class (safe R1, changes R2, consequential R3, destructive R4 + deletes, so it always
asks). The kernel, the owner's never-rules, taint rules, the reliability ledger and the action log therefore apply to
app actions exactly as to every other tool.
"""
from __future__ import annotations

from chutku.apps import atlas as atlas_module
from chutku.apps import runner
from chutku.tools.registry import Risk, Tool, ToolResult, Verification

DRIVER = None   # tests set a fake Driver here; None means the real one


def _make(app_atlas, action):
    schema = atlas_module.param_schema(action)

    def validate(arguments):
        if not isinstance(arguments, dict) or set(arguments) != set(schema["properties"]):
            raise ValueError(f"Give exactly: {', '.join(schema['properties']) or 'no arguments'}.")
        for name, spec in schema["properties"].items():
            value = arguments[name]
            if spec["type"] == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                raise ValueError(f"{name} must be a number")
            if spec["type"] == "string" and (not isinstance(value, str) or not 0 < len(value.strip()) <= 300):
                raise ValueError(f"{name} must be 1-300 characters")

    def execute(arguments, _context):
        result = runner.run(app_atlas, action, arguments, DRIVER)
        return ToolResult(result, Verification.PASS if result.get("ok") else Verification.FAIL)

    risk = atlas_module.RISK[action["risk"]]
    return Tool(f"app.{app_atlas['app']}.{action['id']}",
                f"{app_atlas.get('name', app_atlas['app'])}: {action['title']}", Risk(risk), execute, validate,
                argument_schema=schema, required_capability="desktop.input", reversibility="compensatable" if action["risk"] in {"safe", "changes"} else
                "none", success_predicate="atlas_check_passed", deletes=action["risk"] == "destructive")


def register_app_tools(registry, directory=None):
    """Register every valid atlas's actions; returns {"apps": n, "actions": n, "refused": {file: error}}."""
    atlases, errors = atlas_module.load_all(directory) if directory else atlas_module.load_all()
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

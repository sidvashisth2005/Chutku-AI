"""log.recent ("what did you do today?") and log.undo <id> over the hash-chained action log."""
from __future__ import annotations

from datetime import UTC, datetime

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_RECENT_SCHEMA = {"type": "object", "properties": {
    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
    "today": {"type": "boolean"}}, "additionalProperties": False}
_UNDO_SCHEMA = {"type": "object", "properties": {"id": {"type": "integer", "minimum": 1}},
                "additionalProperties": False}  # no id: the most recent undoable action ("undo that")


def _validate_recent(arguments):
    if set(arguments) - {"limit", "today"}:
        raise ValueError("Provide only limit and today.")
    limit = arguments.get("limit", 20)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")
    if type(arguments.get("today", False)) is not bool:
        raise ValueError("today must be true or false.")


def _validate_undo(arguments):
    if set(arguments) - {"id"} or ("id" in arguments and (type(arguments["id"]) is not int or arguments["id"] < 1)):
        raise ValueError("Provide the action number to undo as id, or nothing for the latest undoable action.")


def _summary(entry):
    return {"id": entry["seq"], "time": entry["time"], "tool": entry["tool"], "state": entry["state"],
            "paths": entry.get("paths", []), "message": entry.get("message"),
            "can_undo": bool(entry.get("undo"))}


def register_action_log_tools(registry, runtime):
    log = runtime.action_log

    def recent(arguments, context):
        since = _utc_midnight() if arguments.get("today") else None
        entries = [_summary(entry) for entry in log.recent(arguments.get("limit", 20), since)]
        chain = log.verify()
        return ToolResult({"actions": entries, "count": len(entries), "chain_ok": chain["ok"],
                           "provenance": "tool_observed"}, Verification.PASS,
                          {"count": len(entries), "chain_ok": chain["ok"], "actions": "[REDACTED]"})

    def undone_ids():
        return {later.get("arguments", {}).get("id") for later in log.recent(10_000)
                if later.get("tool") == "log.undo" and later.get("state") == "COMPLETED"}

    def still_current(entry, context):
        """The journal still holds this action as the latest of its kind (so it has not been undone)."""
        if entry["tool"] == "files.organize":
            return True
        latest = context.journal.latest_completed(entry["tool"], context.granted_root)
        return latest is not None and latest["operation_id"] == entry.get("operation_id")

    def latest_undoable(context):
        done = undone_ids()
        return next((entry for entry in log.recent(200) if entry.get("state") == "COMPLETED" and entry.get("undo")
                     and entry["seq"] not in done and still_current(entry, context)), None)

    def undo(arguments, context):
        if "id" not in arguments:
            entry = latest_undoable(context)
            if entry is None:
                return ToolResult({"error": "There is nothing recent that Chutku can undo."}, Verification.FAIL)
        else:
            entry = log.get(arguments["id"])
        if entry is None:
            return ToolResult({"error": f"There is no action number {arguments['id']}."}, Verification.FAIL)
        undo_name = entry.get("undo")
        if entry.get("state") != "COMPLETED" or not undo_name:
            return ToolResult({"error": "That action has nothing Chutku can undo."}, Verification.FAIL)
        if entry["seq"] in undone_ids():
            return ToolResult({"error": "That action was already undone."}, Verification.FAIL)
        if entry["tool"] == "files.organize":
            undo_arguments = {"id": entry.get("undo_id")}
        else:
            latest = context.journal.latest_completed(entry["tool"], context.granted_root)
            if latest is None or latest["operation_id"] != entry.get("operation_id"):
                return ToolResult({"error": f"Only the most recent {entry['tool']} can be undone, and this is not it "
                                            "(or it was already undone)."}, Verification.FAIL)
            undo_arguments = {"path": entry["paths"][0]} if entry["tool"] == "filesystem.write_text" else {}
        undo_tool = runtime.registry.get(undo_name)
        undo_tool.validate_arguments(undo_arguments)
        reason = runtime.protected_target(undo_tool, undo_arguments)
        if reason is not None:
            return ToolResult({"error": reason}, Verification.FAIL)
        if undo_tool.required_capability is not None:   # the undo is run here directly: re-check its own authority
            try:
                runtime.current_capability(undo_tool.required_capability)
            except ValueError:
                return ToolResult({"error": f"Undoing this needs the {undo_tool.required_capability} capability, "
                                            "which is not granted."}, Verification.FAIL)
        result = undo_tool.execute(undo_arguments, context)
        if undo_tool.verify is not None and result.verification != Verification.FAIL:
            result = undo_tool.verify(undo_arguments, result, context)
        output = dict(result.output) if isinstance(result.output, dict) else {"result": result.output}
        return ToolResult(output | {"undid_action": entry["seq"], "via": undo_name}, result.verification)

    registry.register(Tool("log.recent", "List what Chutku did recently (changes, things it asked about, refusals), "
        "newest first, with action numbers. Use for 'what did you do today?'. today=true limits to today.",
        Risk.OBSERVATION, recent, _validate_recent, argument_schema=_RECENT_SCHEMA,
        reversibility="not_applicable", success_predicate="action_log_read_and_chain_checked"))
    registry.register(Tool("log.undo", "Undo one action from log.recent by its number (or, with no id, the most "
        "recent undoable action: 'undo that'), when it is the most recent action of its kind (writes, copies, moves, "
        "recycles, captures; any folder tidy-up).",
        Risk.DATA_MODIFICATION, undo, _validate_undo, resource_access="modify", argument_schema=_UNDO_SCHEMA,
        reversibility="journaled", success_predicate="undo_tool_verified"))


def _utc_midnight():
    """Entries are stored in UTC; the user's "today" starts at local midnight."""
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC).isoformat(timespec="seconds")

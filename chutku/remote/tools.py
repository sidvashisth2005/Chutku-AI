"""Phone access by voice or chat at the laptop (W6): "phone connect karo", "phone pair karo", "remote band karo",
"phone hatao", "phone control on karo". Every remote.* step is laptop-only: the phone itself can never approve one
(chutku/remote/server.py LAPTOP_ONLY_PREFIXES), so a phone can't widen its own access."""
from __future__ import annotations

from chutku.tools.registry import Risk, Tool, ToolResult, Verification

_NONE = {"type": "object", "properties": {}, "additionalProperties": False}


def _manager():
    from chutku.remote.manager import current
    manager = current()
    if manager is None:
        raise OSError("Phone access works only while Chutku's dashboard is running.")
    return manager


def _status(arguments, context):
    status = _manager().status()
    return ToolResult({k: status[k] for k in ("enabled", "running", "url", "control_allowed", "phone_active",
                                               "viewing", "controlling")} | {"phones": [d["name"] for d in status["devices"]
                                                                                       if not d.get("revoked")]},
                      Verification.PASS)


def _enable(arguments, context):
    result = _manager().enable()
    return ToolResult(result, Verification.PASS if result.get("enabled") else Verification.FAIL)


def _disable(arguments, context):
    return ToolResult(_manager().disable(), Verification.PASS)


def _pair(arguments, context):
    result = _manager().pair_code()
    if "error" in result:
        return ToolResult(result, Verification.FAIL)
    # The code is shown on the laptop (dashboard Phone panel); it is not written to the audit trail.
    return ToolResult({"code": result["code"], "link": result["link"], "minutes": result["minutes"],
                       "note": "Open the link on the phone (or scan the QR in the dashboard's Phone panel)."},
                      Verification.PASS, {"code": "[REDACTED]", "minutes": result["minutes"]})


def _revoke(arguments, context):
    manager = _manager()
    devices = [d for d in manager.status()["devices"] if not d.get("revoked")]
    wanted = str(arguments.get("phone") or "all").casefold()
    chosen = devices if wanted == "all" else [d for d in devices if d["name"].casefold() == wanted or d["id"] == wanted]
    if not chosen:
        return ToolResult({"error": "No paired phone with that name.", "phones": [d["name"] for d in devices]},
                          Verification.FAIL)
    for device in chosen:
        manager.revoke(device["id"])
    return ToolResult({"removed": [d["name"] for d in chosen]}, Verification.PASS)


def _arm(arguments, context):
    return ToolResult(_manager().arm(bool(arguments["on"])), Verification.PASS)


def _check(allowed):
    def validate(arguments):
        if not isinstance(arguments, dict) or set(arguments) - set(allowed):
            raise ValueError("Unexpected arguments.")
        if "on" in allowed and type(arguments.get("on")) is not bool:
            raise ValueError("on must be true or false.")
        if "phone" in arguments and (not isinstance(arguments["phone"], str) or len(arguments["phone"]) > 40):
            raise ValueError("phone must be a name.")
    return validate


def register_remote_tools(registry):
    registry.register(Tool("remote.status", "Phone access: on or off, paired phones, whether a phone is connected, "
                           "watching the screen or controlling.", Risk.OBSERVATION, _status, _check(()),
                           argument_schema=_NONE, reversibility="not_applicable", success_predicate="status_returned"))
    registry.register(Tool("remote.enable", "Turn on phone access through the owner's own Tailscale network (HTTPS, "
                           "tailnet only, never the public internet).", Risk.EXTERNAL_SIDE_EFFECT, _enable, _check(()),
                           argument_schema=_NONE, reversibility="compensatable", success_predicate="tailnet_serving"))
    registry.register(Tool("remote.disable", "Turn phone access off: stops the phone server and Tailscale serve, "
                           "ends every phone session.", Risk.REVERSIBLE, _disable, _check(()), argument_schema=_NONE,
                           reversibility="compensatable", success_predicate="phone_server_stopped"))
    registry.register(Tool("remote.pair", "Make a one-time pairing code (10 minutes) for a new phone, shown on the "
                           "laptop.", Risk.REVERSIBLE, _pair, _check(()), argument_schema=_NONE,
                           reversibility="transient", success_predicate="pairing_code_created"))
    registry.register(Tool("remote.revoke", "Remove a paired phone (by name) or all phones: they must pair again.",
                           Risk.DATA_MODIFICATION, _revoke, _check(("phone",)),
                           argument_schema={"type": "object", "properties": {"phone": {"type": "string", "maxLength": 40}},
                                            "additionalProperties": False},
                           reversibility="compensatable", success_predicate="device_revoked"))
    registry.register(Tool("remote.arm", "Allow (on) or forbid (off) direct mouse and keyboard control from the "
                           "paired phone. Only at the laptop.", Risk.EXTERNAL_SIDE_EFFECT, _arm, _check(("on",)),
                           argument_schema={"type": "object", "properties": {"on": {"type": "boolean"}},
                                            "required": ["on"], "additionalProperties": False},
                           reversibility="compensatable", success_predicate="control_setting_written"))

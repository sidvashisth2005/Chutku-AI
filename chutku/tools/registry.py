from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from enum import IntEnum, StrEnum
import hashlib
import json
from typing import TYPE_CHECKING, Any
from pathlib import Path

if TYPE_CHECKING:
    from chutku.core.operation_journal import OperationJournal
    from chutku.core.memory import MemoryStore


class Risk(IntEnum):
    OBSERVATION = 0
    REVERSIBLE = 1
    DATA_MODIFICATION = 2
    EXTERNAL_SIDE_EFFECT = 3
    DESTRUCTIVE_OR_PRIVILEGED = 4
    DISABLED = 5


class Verification(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


EMPTY_ARGUMENT_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def check_schema(value: Any, schema: dict[str, Any] | None, where: str = "arguments") -> None:
    """Strictly check a value against the JSON-schema subset used by tool manifests.

    Unknown keywords are ignored only if they are annotations; a missing schema fails closed.
    """
    import re
    if not isinstance(schema, dict):
        raise ValueError(f"{where}: tool has no argument schema.")
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                check_schema(value, option, where)
                matches += 1
            except ValueError:
                pass
        if matches != 1:
            raise ValueError(f"{where}: must match exactly one allowed form.")
    kind = schema.get("type")
    if kind == "integer":
        if type(value) is not int:
            raise ValueError(f"{where}: must be an integer.")
    elif kind == "number":
        if type(value) not in (int, float):
            raise ValueError(f"{where}: must be a number.")
    elif kind is not None:
        if kind not in _TYPES or type(value) is not _TYPES[kind]:
            raise ValueError(f"{where}: must be {kind}.")
    if "enum" in schema and value not in schema["enum"]:
        allowed = ", ".join(map(str, schema["enum"][:40]))
        raise ValueError(f"{where}: {str(value)[:40]!r} is not allowed; use one of: {allowed}.")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10**9):
            raise ValueError(f"{where}: length out of range.")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{where}: invalid format.")
    if type(value) in (int, float):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            raise ValueError(f"{where}: out of range.")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", 10**9):
            raise ValueError(f"{where}: wrong number of items.")
        if "items" in schema:
            for index, item in enumerate(value):
                check_schema(item, schema["items"], f"{where}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ValueError(f"{where}: missing '{key}'.")
        for key, item in value.items():
            if key in properties:
                check_schema(item, properties[key], f"{where}.{key}")
            elif schema.get("additionalProperties", True) is False:
                raise ValueError(f"{where}: unexpected '{key}'.")
            elif isinstance(schema.get("additionalProperties"), dict):
                check_schema(item, schema["additionalProperties"], f"{where}.{key}")


@dataclass(frozen=True)
class ToolResult:
    output: dict[str, Any]
    verification: Verification
    audit_output: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionContext:
    task_id: str
    journal: "OperationJournal"
    granted_root: Path
    memory: "MemoryStore | None" = None
    capability_grants: Any = None     # this runtime's PC capability grants (e.g. may Gemini be the backup?)
    approved: bool = False            # the owner confirmed this exact step on screen
    autonomy: str | None = None       # the request's autonomy mode (a scheduled task later runs in the same mode)
    provenance: str | None = None     # who asked: user_stated, delegated or delegated_microphone

    def granted(self, capability):
        if self.capability_grants is None:
            return False
        try:
            self.capability_grants.get(capability)
            return True
        except (ValueError, KeyError, OSError):
            return False


Execute = Callable[[dict[str, Any], ExecutionContext], ToolResult]
ValidateArguments = Callable[[dict[str, Any]], None]
Verify = Callable[[dict[str, Any], ToolResult, ExecutionContext], ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    base_risk: Risk
    execute: Execute
    validate_arguments: ValidateArguments = lambda _: None
    sensitive_argument_names: frozenset[str] = frozenset()
    verify: Verify | None = None
    resource_access: str | None = None
    required_capability: str | None = None
    argument_schema: dict[str, Any] | None = None
    prerequisites: tuple[str, ...] = ()
    reversibility: str = "none"
    success_predicate: str = "tool_result_verification"
    network_egress: bool = False  # sends data off the machine (e.g. a URL request)
    deletes: bool = False  # removes the user's data (even recoverably): always asked first
    user_only: bool = False  # only the user may request it; an agent or observed content never can
    runs_code: bool = False  # runs a script or a program with arguments: confirmed on screen in every mode

    def manifest(self) -> dict[str, Any]:
        """Return the non-executable contract exposed to planners and reviewers."""
        return {
            "name": self.name,
            "description": self.description,
            "risk": {"level": int(self.base_risk), "name": self.base_risk.name.lower()},
            "argument_schema": deepcopy(self.argument_schema),
            "required_capability": self.required_capability,
            "resource_access": self.resource_access,
            "sensitive_argument_names": sorted(self.sensitive_argument_names),
            "prerequisites": list(self.prerequisites),
            "reversibility": self.reversibility,
            "success_predicate": self.success_predicate,
            "independent_verifier": self.verify is not None,
        } | ({"network_egress": True} if self.network_egress else {}) | (
            {"deletes": True} if self.deletes else {}) | ({"user_only": True} if self.user_only else {}) | (
            {"runs_code": True} if self.runs_code else {})

    def manifest_version(self) -> str:
        encoded = json.dumps(self.manifest(), sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool registration: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as error:
            raise KeyError(f"Unknown tool: {name}") from error

    def list(self) -> list[Tool]:
        return list(self._tools.values())

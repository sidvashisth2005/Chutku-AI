from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from chutku.core.ledger import unreliable
from chutku.tools.registry import Risk, Tool


class Decision(StrEnum):
    ALLOW = "ALLOW"
    CONFIRM = "CONFIRM"
    DENY = "DENY"


@dataclass(frozen=True)
class Authorization:
    decision: Decision
    risk: Risk
    reason: str


class AutonomyMode(StrEnum):
    """User-selected ceiling for steps an agent may run without a per-step click."""
    REVIEW = "review"          # nothing runs until the user approves the proposed steps
    AUTO_SAFE = "auto_safe"    # observation and easily reversible steps (<= R1)
    AUTO_EDITS = "auto_edits"  # also journaled/compensatable data changes (<= R2)
    OWNER = "owner"            # the owner's standing order: everything runs, except changing or deleting files,
                               # deletions of any kind, power/kill/network-off (R4) and messages to unknown people


DELEGATED_PROVENANCE = frozenset({"delegated", "delegated_microphone"})
# A user-only tool needs the user's own typed request, or a spoken one they reviewed.
USER_ONLY_PROVENANCE = frozenset({"user_stated", "reviewed_microphone"})
_CEILING = {AutonomyMode.REVIEW: None, AutonomyMode.AUTO_SAFE: Risk.REVERSIBLE,
            AutonomyMode.AUTO_EDITS: Risk.DATA_MODIFICATION, AutonomyMode.OWNER: Risk.EXTERNAL_SIDE_EFFECT}
# An automatically-run data change must have a runtime-owned way back.
AUTO_EDIT_REVERSIBILITY = frozenset({"journaled", "compensatable", "single_use", "transient"})
# File tools that only ever create something new (they never change or remove an existing file).
# Reversible (R1) steps that still ask right after Chutku read outside content (a web page, a message, the clipboard),
# because they start programs, open files, change what Chutku remembers, or turn the cloud back on.
TAINT_SENSITIVE_R1 = ("apps.launch", "files.open", "mind.", "memory.remember", "settings.offline_mode",
                      "task.schedule")   # a page must never plant a task that runs later by itself
# Content Chutku read contained instruction-like text (a page or message trying to steer her, master plan S15):
# from then on every step that changes anything waits for the owner, in every mode.
SUSPICIOUS_REASON = "What Chutku read tried to give her instructions; every change now waits for your click."
TAINT_R1_REASON = "This step follows content read from outside; confirm it."
RUNS_CODE_REASON ="Running code or a program with arguments always asks first."
CREATE_ONLY_TOOLS = frozenset({"filesystem.create_directory", "files.zip", "files.unzip", "code.build_project",
                               "screen.capture"})


def earned_file_change(tool, tainted, reliability, relax):
    """The owner's opt-in "earned autonomy relax on": a file change that can be undone and has worked 20+ times
    in a row (no failure in the last 20) on this exact target no longer asks. Never for deletes or after reading
    outside content. Off unless the owner said so (master plan S16)."""
    return (relax is True and not tainted and not tool.deletes and tool.reversibility in AUTO_EDIT_REVERSIBILITY
            and reliability is not None and reliability.n >= 20 and reliability.recent_failures == 0)


class PolicyKernel:
    """Small fail-closed policy kernel; expand rules before adding mutating tools."""

    def authorize(self, tool: Tool, arguments: dict[str, Any], confirmed_on_screen: bool = False, *, provenance="user_stated", resource_access=None, capability_allowed=None, autonomy=None, tainted=False, protected_reason=None, exposed=None, owner_question=None, suspicious=False, reliability=None, relax=False) -> Authorization:
        del arguments  # Risk is runtime-owned; caller-provided risk is deliberately ignored.
        risk = tool.base_risk
        if tool.resource_access is not None and (resource_access is None or tool.resource_access not in resource_access):
            return Authorization(Decision.DENY, risk, "The selected resource grant does not allow this operation.")
        if tool.required_capability is not None and capability_allowed is not True:
            return Authorization(Decision.DENY, risk, "The required PC capability has not been explicitly granted.")
        if protected_reason is not None:
            return Authorization(Decision.DENY, risk, str(protected_reason))
        if tool.user_only and provenance not in USER_ONLY_PROVENANCE:
            return Authorization(Decision.DENY, risk, "Only you can ask for this directly; Chutku never chooses it by itself.")
        if provenance in DELEGATED_PROVENANCE:
            return self._delegated(tool, risk, confirmed_on_screen, autonomy, tainted,
                                   tainted if exposed is None else exposed, owner_question, suspicious,
                                   reliability, relax)
        if autonomy is not None:
            return Authorization(Decision.DENY, risk, "An autonomy mode applies only to delegated agent steps.")
        if provenance not in {"user_stated", "external_untrusted", "microphone_untrusted", "tool_observed", "inferred",
                              "reviewed_inferred", "reviewed_microphone"}:
            return Authorization(Decision.DENY, risk, "Unknown instruction provenance.")
        if provenance in {"external_untrusted", "microphone_untrusted", "tool_observed", "inferred"} and risk >= Risk.DATA_MODIFICATION:
            return Authorization(Decision.DENY, risk, "Untrusted or inferred content cannot authorize data modifications or external actions.")
        if risk == Risk.DISABLED:
            return Authorization(Decision.DENY, risk, "This operation class is disabled.")
        if tool.runs_code and not confirmed_on_screen:
            return Authorization(Decision.CONFIRM, risk, RUNS_CODE_REASON)
        if risk >= Risk.EXTERNAL_SIDE_EFFECT and not confirmed_on_screen:
            return Authorization(Decision.CONFIRM, risk, "On-screen confirmation is required for this risk level.")
        if tool.deletes and not confirmed_on_screen:
            return Authorization(Decision.CONFIRM, risk, "Deleting always asks first.")
        return Authorization(Decision.ALLOW, risk, "Allowed by current policy.")

    @staticmethod
    def _delegated(tool: Tool, risk: Risk, confirmed_on_screen: bool, autonomy, tainted, exposed,
                   owner_question=None, suspicious=False, reliability=None, relax=False) -> Authorization:
        """Agent-proposed step for a user-stated goal, bounded by the chosen mode."""
        try:
            mode = AutonomyMode(autonomy)
        except ValueError:
            return Authorization(Decision.DENY, risk, "Unknown or missing autonomy mode.")
        if type(tainted) is not bool or type(exposed) is not bool:
            return Authorization(Decision.DENY, risk, "Invalid taint state.")
        if risk == Risk.DISABLED:
            return Authorization(Decision.DENY, risk, "This operation class is disabled.")
        if confirmed_on_screen:
            return Authorization(Decision.ALLOW, risk, "Confirmed on screen for this exact step.")
        if tool.runs_code:
            return Authorization(Decision.CONFIRM, risk, RUNS_CODE_REASON)
        if tool.deletes:
            return Authorization(Decision.CONFIRM, risk, "Deleting always asks first.")
        if owner_question:  # a step-specific question (unknown recipient, file-changing keys) asks in every mode
            return Authorization(Decision.CONFIRM, risk, str(owner_question))
        if suspicious and risk >= Risk.REVERSIBLE:
            return Authorization(Decision.CONFIRM, risk, SUSPICIOUS_REASON)
        if tainted and risk >= Risk.REVERSIBLE and tool.name.startswith(TAINT_SENSITIVE_R1):
            return Authorization(Decision.CONFIRM, risk, TAINT_R1_REASON)
        if risk >= Risk.REVERSIBLE and unreliable(reliability):
            # Earned autonomy (master plan S16): this kind of step keeps failing, so it asks, in every mode.
            return Authorization(Decision.CONFIRM, risk, f"This has worked {reliability.passes} of the last "
                                 f"{reliability.n} times ({reliability.key}); confirm it.")
        if mode == AutonomyMode.OWNER:
            return PolicyKernel._owner(tool, risk, tainted, exposed, owner_question, reliability, relax)
        ceiling = _CEILING[mode]
        if ceiling is None or risk > ceiling:
            return Authorization(Decision.CONFIRM, risk, f"Mode '{mode.value}' requires on-screen confirmation for this step.")
        if risk >= Risk.DATA_MODIFICATION:
            if tainted:
                return Authorization(Decision.CONFIRM, risk, "This change follows untrusted observed content; confirm it on screen.")
            if tool.reversibility not in AUTO_EDIT_REVERSIBILITY:
                return Authorization(Decision.CONFIRM, risk, "This change has no runtime undo; confirm it on screen.")
        if exposed and tool.network_egress:
            # Private data (files, clipboard, screen, memory) was read: a URL built from it could leak it.
            # After public web content only, there is nothing private to leak.
            return Authorization(Decision.CONFIRM, risk, "A network request after reading untrusted content needs on-screen confirmation.")
        return Authorization(Decision.ALLOW, risk, f"Allowed automatically by mode '{mode.value}'.")

    @staticmethod
    def _owner(tool: Tool, risk: Risk, tainted, exposed, owner_question, reliability=None,
               relax=False) -> Authorization:
        """The owner's standing order (2026-10-04): do everything without asking, except file changes and deletions."""
        if risk >= Risk.DESTRUCTIVE_OR_PRIVILEGED:
            return Authorization(Decision.CONFIRM, risk, "Power, killing a program or turning the network off can lose "
                                 "unsaved work; this asks first.")
        if tool.resource_access == "modify" and tool.name not in CREATE_ONLY_TOOLS                 and not earned_file_change(tool, tainted, reliability, relax):
            return Authorization(Decision.CONFIRM, risk, "Changing files always asks first.")
        if owner_question:
            return Authorization(Decision.CONFIRM, risk, str(owner_question))
        if tainted and risk >= Risk.DATA_MODIFICATION:
            # Text read from a web page or a message must not be able to make Chutku act on its own.
            return Authorization(Decision.CONFIRM, risk, "This step follows content read from outside; confirm it.")
        if exposed and tool.network_egress:
            return Authorization(Decision.CONFIRM, risk, "A network request after reading untrusted content needs on-screen confirmation.")
        return Authorization(Decision.ALLOW, risk, "Allowed automatically by your standing order (owner mode).")

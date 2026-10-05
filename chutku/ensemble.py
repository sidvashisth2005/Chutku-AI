"""Deterministic reconciliation for independently produced model proposals."""
from __future__ import annotations

from chutku.brain import MODEL_NAME, validate_plan


def reconcile_plans(local, gemini, *, gemini_model="Gemini", gemini_usage=None):
    """Select exact executable agreement; disagreement cannot authorize action."""
    local_core = validate_plan({key: local[key] for key in ("reply", "commands", "needs_clarification")})
    gemini_core = validate_plan({key: gemini[key] for key in ("reply", "commands", "needs_clarification")})
    same = (local_core["commands"] == gemini_core["commands"]
            and local_core["needs_clarification"] == gemini_core["needs_clarification"])
    consultation = {"local": local.get("model", MODEL_NAME), "gemini": gemini_model,
                    "decision": "consensus" if same else "clarification",
                    "gemini_usage": gemini_usage or {}}
    if same:
        return {**local, "consultation": consultation,
                "router": local.get("router", "local_llm") + "+gemini_consensus"}
    return {"reply": "The local and Gemini planners disagreed, so no action was proposed. Please clarify the exact intended action.",
            "commands": [], "needs_clarification": True, "model": local.get("model", MODEL_NAME),
            "inference_seconds": local.get("inference_seconds", 0.0), "usage": local.get("usage", {}),
            "experimental": True, "router": "dual_model_disagreement", "consultation": consultation}

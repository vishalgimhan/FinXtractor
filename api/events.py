"""Serialization helpers shared by the streaming endpoint.

Turns LangGraph node updates into small, JSON-safe Server-Sent Events, and the
final pipeline state into the same cache schema the dashboard already knows how
to hydrate (see dashboard.hydrate_state / save_cache)."""
from __future__ import annotations

import json
from typing import Any

# Graph node -> human label. Order mirrors the happy path through the graph.
NODE_LABELS: dict[str, str] = {
    "resolver": "Locating statement pages",
    "extractor": "Extracting line items",
    "vlm": "Vision fallback (VLM)",
    "validator": "Cross-foot validation",
    "retry": "Retrying extraction",
    "hitl": "Flagged for human review",
    "scoring": "Scoring & credit analysis",
}


def sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event frame (`event:`/`data:` + blank line)."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _dump(obj: Any) -> Any:
    """JSON-safe dump of a pydantic model (or pass-through for plain values)."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump_json"):
        return json.loads(obj.model_dump_json())
    return obj


def stage_payload(node: str, update: dict) -> dict:
    """Small per-stage event: which node finished plus a few human-readable deltas.

    Deliberately lightweight — the full result is sent once in the `done` event."""
    deltas: dict[str, Any] = {}
    if isinstance(update, dict):
        for key in ("route", "income_page", "bs_page", "income_page_source",
                    "bs_page_source", "text_layer", "retries", "resolution_error"):
            val = update.get(key)
            if val is not None:
                deltas[key] = val

        checks = update.get("checks")
        if checks:
            deltas["checks_total"] = len(checks)
            deltas["checks_failed"] = sum(
                1 for c in checks if getattr(c.status, "value", c.status) == "fail"
            )

        stmt = update.get("statement")
        if stmt is not None:
            deltas["line_items"] = len(stmt.lines)

        credit = update.get("credit_report")
        if credit is not None and getattr(credit, "composite", None) is not None:
            deltas["grade"] = credit.composite.grade

    status = "fail" if (node == "hitl" or "resolution_error" in deltas) else "done"
    return {"node": node, "label": NODE_LABELS.get(node, node),
            "status": status, "deltas": deltas}


def serialize_final(state: dict) -> dict:
    """Serialize the final graph state into the dashboard's cache schema."""
    return {
        "pdf": state.get("pdf"),
        "income_page": state.get("income_page"),
        "bs_page": state.get("bs_page"),
        "income_page_source": state.get("income_page_source"),
        "bs_page_source": state.get("bs_page_source"),
        "text_layer": state.get("text_layer", "ok"),
        "route": state.get("route"),
        "retries": state.get("retries", 0),
        "statement": _dump(state.get("statement")),
        "checks": [_dump(c) for c in state.get("checks", [])],
        "confidences": [_dump(c) for c in state.get("confidences", [])],
        "report": _dump(state.get("report")),
        "credit_report": _dump(state.get("credit_report")),
    }

from typing import Literal
from .state import PipelineState
from ..validate.results import CheckStatus


def route_after_resolver(state: PipelineState) -> Literal["extract", "vlm", "unresolved"]:
    """After the Resolver: a still-missing page on a scan goes to the shared VLM
    node; a located income page proceeds to extraction; otherwise HITL."""
    if state.get("route") == "vlm":
        return "vlm"
    return "extract" if state.get("income_page") is not None else "unresolved"


def route_after_vlm(state: PipelineState) -> Literal["extractor", "validator", "hitl"]:
    """After the shared VLM node, by the route it set: a located page -> extractor
    (task=locate), a read table -> validator (task=extract), a miss -> HITL."""
    route = state.get("route")
    if route == "unresolved":
        return "hitl"
    if route == "validate":
        return "validator"
    return "extractor"                       # 'resolved' — VLM located the page


def route_after_extractor(state: PipelineState) -> Literal["vlm", "validate"]:
    """After the Extractor: a page its text tiers couldn't read goes to the VLM
    node (task=extract); otherwise straight to validation."""
    return "vlm" if state.get("route") == "vlm" else "validate"


def route_after_validation(state: PipelineState) -> Literal["retry", "hitl", "proceed"]:
    """Decide where to go after the Validator. Reads state only — no side effects."""
    checks = state.get("checks", [])
    failed = sum(1 for c in checks if c.status == CheckStatus.FAIL)
    retries = state.get("retries", 0)
    max_retries = state.get("max_retries", 2)
    prev_failed = state.get("prev_failed_count")   # failures before the last retry; None on first pass
    report = state.get("report")

    # 1. Retry only while failures remain, budget is left, AND the previous
    #    attempt actually reduced the failure count (prev is None on first pass).
    #    This stops the loop from re-extracting identically with no improvement.
    improved = prev_failed is None or failed < prev_failed
    if failed > 0 and retries < max_retries and improved:
        return "retry"

    # 2. Anything flagged for review (incl. failures we couldn't fix) -> human.
    if report and report.flagged_count > 0:
        return "hitl"

    # 3. Clean and confident -> proceed to scoring.
    return "proceed"

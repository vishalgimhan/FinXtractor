from typing import Literal
from .state import PipelineState
from ..validate.results import CheckStatus


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

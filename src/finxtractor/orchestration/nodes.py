from .state import PipelineState
from ..parsing.vlm_fallback import extract_income_statement
from ..parsing.notes import resolve_line_item_notes
from ..normalize.normalize import normalize, pull_balance_sheet, merge
from ..validate.checks import run_all_checks
from ..validate.confidence import score_statement
from ..validate.hitl import build_report
from ..validate.results import CheckStatus


def extractor_node(state: PipelineState) -> dict:
    """Extract income + balance sheet, normalize to canonical. (Extractor + Normalizer.)"""
    pdf, ip, bsp = state["pdf"], state["income_page"], state.get("bs_page")
    raw = extract_income_statement(pdf, ip)
    resolve_line_item_notes(raw)
    income = normalize(raw)
    full = merge(income, pull_balance_sheet(pdf, bsp))
    return {"statement": full}

def validator_node(state: PipelineState) -> dict:
    """Run cross-foot checks, score confidence, apply the HITL gate. (Validator.)"""
    stmt = state["statement"]
    checks = run_all_checks(stmt)
    confidences = score_statement(stmt, checks)
    report = build_report(checks, confidences, state.get("retries", 0))
    return {"checks": checks, "confidences": confidences, "report": report}

def retry_node(state: PipelineState) -> dict:
    """Bump the retry counter and record the failure count we're trying to beat,
    so the router can stop if the next attempt doesn't improve. (Retry loop edge.)"""
    failed = sum(1 for c in state.get("checks", []) if c.status == CheckStatus.FAIL)
    return {"retries": state.get("retries", 0) + 1, "prev_failed_count": failed}

def hitl_node(state: PipelineState) -> dict:
    """Surface flagged values for human review. (HITL terminal for this run.)"""
    report = state["report"]
    flagged = [vc for vc in report.confidences if vc.flagged_for_review]
    # In production: interrupt() here to pause for a real reviewer and resume on input.
    return {"route": "hitl", "report": report,
            "confidences": report.confidences,
            # annotate so a downstream consumer/log sees the review queue
            }

def scoring_node(state: PipelineState) -> dict:
    """Clean data proceeds here — finalize. (Scoring entry point; Phase 7 expands it.)"""
    return {"route": "scoring", "report": state["report"]}


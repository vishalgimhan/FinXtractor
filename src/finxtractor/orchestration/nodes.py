from .state import PipelineState
from ..parsing.statements import extract_canonical
from ..normalize.normalize import merge
from ..validate.checks import run_all_checks
from ..validate.confidence import score_statement
from ..validate.hitl import build_report
from ..validate.results import CheckStatus


def extractor_node(state: PipelineState) -> dict:
    """Extract income + balance sheet to canonical and merge. (Extractor + Normalizer.)"""
    pdf, ip, bsp = state["pdf"], state["income_page"], state.get("bs_page")
    income = extract_canonical(pdf, ip)
    balance_sheet = extract_canonical(pdf, bsp)
    full = merge(income, balance_sheet)
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


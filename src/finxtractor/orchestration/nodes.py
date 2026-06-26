from .state import PipelineState
from ..agents.resolver import resolve
from ..parsing.statements import extract_canonical
from ..normalize.normalize import merge
from ..validate.checks import run_all_checks
from ..validate.confidence import score_statement
from ..validate.hitl import build_report
from ..validate.results import CheckResult, CheckStatus, ValidationReport
from ..scoring.ratios import compute_ratios
from ..scoring.altman import compute_altman
from ..scoring.composite import compute_composite
from ..scoring.risk import compute_risk
from ..scoring.schemas import CreditReport

def resolver_agent(state: PipelineState) -> dict:
    """Locate the statement pages via the resolver agent — an LLM that drives the
    location tiers (extract -> triage -> index -> printed-TOC/heuristic -> OCR/VLM
    scan) through tools and decides when to stop. Falls back to the deterministic
    cascade if the LLM tier is down. The page index is built once and carried in
    state for reuse. (Resolver.)"""
    return resolve(state["pdf"], state.get("income_page"), state.get("bs_page"))

def extractor_node(state: PipelineState) -> dict:
    """Extract income (+ balance sheet, if located) to canonical and merge.
    Pages and text_layer come from the resolver; text_layer drives the
    TableFormer -> OCR -> VLM ladder. (Extractor + Normalizer.)"""
    pdf, ip, bsp = state["pdf"], state["income_page"], state.get("bs_page")
    layer = state.get("text_layer", "ok")
    income = extract_canonical(pdf, ip, text_layer=layer)
    full = merge(income, extract_canonical(pdf, bsp, text_layer=layer)) if bsp is not None else income
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
    """Surface items needing human review. (HITL terminal for this run.)
    Two entries: a validation that flagged values, or a resolution failure
    (no statement page located) routed straight here."""
    report = state.get("report")
    if report is None:
        # Resolution failure: nothing was extracted/validated. Build a report so
        # downstream consumers (orchestrator/CLI) see a flagged, inspectable result.
        msg = state.get("resolution_error", "Could not locate statement pages")
        report = ValidationReport(
            checks=[CheckResult(name="page_resolution", status=CheckStatus.FAIL, message=msg)],
            flagged_count=1,
        )
        return {"route": "hitl", "report": report, "confidences": []}
    # In production: interrupt() here to pause for a real reviewer and resume on input.
    return {"route": "hitl", "report": report, "confidences": report.confidences}

def scoring_node(state: PipelineState) -> dict:
    """Compute ratios, Altman Z'', the composite credit score, and structured
    risk flags (threshold breaches, YoY deterioration, data quality). (Scoring.)"""
    stmt = state["statement"]
    ratios = compute_ratios(stmt)
    altman = compute_altman(stmt)
    composite = compute_composite(ratios, altman)
    risk_flags = compute_risk(stmt, ratios, altman, state.get("checks"))
    credit = CreditReport(source_pdf=stmt.source_pdf, year=stmt.year_current,
                          ratios=ratios, altman=altman, composite=composite,
                          risk_flags=risk_flags)
    return {"route": "scoring", "credit_report": credit}


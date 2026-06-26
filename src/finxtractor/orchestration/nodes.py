from pathlib import Path

from loguru import logger

from .state import PipelineState
from ..parsing.routing import resolve_page, INCOME_MARKERS, BALANCE_SHEET_MARKERS
from ..parsing.text import extract_pages
from ..agents.toc import get_structured_toc
from ..parsing.statements import extract_canonical
from ..normalize.normalize import merge
from ..validate.checks import run_all_checks
from ..validate.confidence import score_statement
from ..validate.hitl import build_report
from ..validate.results import CheckStatus
from ..scoring.ratios import compute_ratios
from ..scoring.altman import compute_altman
from ..scoring.composite import compute_composite
from ..scoring.schemas import CreditReport

def resolver_node(state: PipelineState) -> dict:
    """Locate the statement pages. Precedence per page: explicit override ->
    agentic structured TOC (LLM) -> deterministic TOC/outline/heuristic. The
    structured TOC is parsed once and carried in state for reuse. (Resolver.)"""
    pdf = Path(state["pdf"])
    pages = extract_pages(pdf)
    toc = get_structured_toc(pdf)        # agentic + cached; None -> deterministic fallback

    def locate(override, markers):
        if override is not None:
            return override, "override"
        if toc is not None:
            p = toc.resolve(markers)
            if p is not None and 1 <= p <= len(pages):
                return p, "agentic_toc"
        return resolve_page(pdf, pages, markers)

    ip, ip_source = locate(state.get("income_page"), INCOME_MARKERS)
    if ip is None:
        raise ValueError(f"Could not resolve an income-statement page in {pdf.name}")
    bsp, bsp_source = locate(state.get("bs_page"), BALANCE_SHEET_MARKERS)

    logger.info("Resolved pages for {}: income={} ({}), balance={} ({})",
                pdf.name, ip, ip_source, bsp, bsp_source)
    return {"income_page": ip, "bs_page": bsp,
            "income_page_source": ip_source, "bs_page_source": bsp_source,
            "toc": toc, "route": "resolved"}

def extractor_node(state: PipelineState) -> dict:
    """Extract income (+ balance sheet, if located) to canonical and merge.
    Pages come from the resolver. (Extractor + Normalizer.)"""
    pdf, ip, bsp = state["pdf"], state["income_page"], state.get("bs_page")
    income = extract_canonical(pdf, ip)
    full = merge(income, extract_canonical(pdf, bsp)) if bsp is not None else income
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
    """Compute ratios, Altman Z'', and the composite credit score. (Scoring.)"""
    stmt = state["statement"]
    ratios = compute_ratios(stmt)
    altman = compute_altman(stmt)
    composite = compute_composite(ratios, altman)
    credit = CreditReport(source_pdf=stmt.source_pdf, year=stmt.year_current,
                          ratios=ratios, altman=altman, composite=composite)
    return {"route": "scoring", "credit_report": credit}


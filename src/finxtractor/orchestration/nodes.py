from pathlib import Path

from loguru import logger

from .state import PipelineState
from ..parsing.routing import resolve_page, page_from_outline, INCOME_MARKERS, BALANCE_SHEET_MARKERS
from ..parsing.text import extract_pages, assess_text_layer
from ..services.pdf_reader import get_pdf_reader
from ..agents.toc import get_structured_toc
from ..agents.page_locator import locate_scanned
from ..parsing.statements import extract_canonical
from ..normalize.normalize import merge
from ..validate.checks import run_all_checks
from ..validate.confidence import score_statement
from ..validate.hitl import build_report
from ..validate.results import CheckResult, CheckStatus, ValidationReport
from ..scoring.ratios import compute_ratios
from ..scoring.altman import compute_altman
from ..scoring.composite import compute_composite
from ..scoring.schemas import CreditReport

def resolver_node(state: PipelineState) -> dict:
    """Locate the statement pages. Precedence per page: explicit override ->
    agentic structured TOC (LLM) -> deterministic TOC/outline/heuristic. The
    structured TOC is parsed once and carried in state for reuse. (Resolver.)"""
    pdf = Path(state["pdf"])
    pages = extract_pages(pdf)                 # one text read
    embedded_outline = get_pdf_reader().outline(pdf)  # one bookmark read, reused per kind
    layer = assess_text_layer(pages)
    toc = get_structured_toc(pages)       # agentic; built from pages, held in state below
    logger.info("Triage for {}: text_layer={}", pdf.name, layer)

    def locate(override, markers):
        """override -> agentic TOC -> deterministic (text). None if all miss."""
        if override is not None:
            return override, "override"
        if toc is not None:
            p = toc.resolve(markers)
            if p is not None and 1 <= p <= len(pages):
                return p, "agentic_toc"
        if layer != "none":               # text-based tiers are pointless on a scan
            return resolve_page(pdf, pages, markers, outline=embedded_outline)
        # scanned: text tiers can't help, but bookmarks may still exist
        p = page_from_outline(pdf, markers, outline=embedded_outline)
        return (p, "outline") if p is not None else (None, None)

    ip, ip_source = locate(state.get("income_page"), INCOME_MARKERS)
    bsp, bsp_source = locate(state.get("bs_page"), BALANCE_SHEET_MARKERS)

    # Escalate to the scan locator (OCR pages -> rank; VLM-classify the rest) when
    # text tiers couldn't find income, or the PDF is scanned.
    missing = {}
    if ip is None:
        missing["income"] = INCOME_MARKERS
    if bsp is None:
        missing["balance"] = BALANCE_SHEET_MARKERS
    if missing and (layer == "none" or ip is None):
        scanned = locate_scanned(pdf, len(pages), missing, text_layer=layer)
        if "income" in scanned:
            ip, ip_source = scanned["income"]
        if "balance" in scanned:
            bsp, bsp_source = scanned["balance"]

    if ip is None:
        # Graceful: no crash. Route to HITL with a clear, inspectable reason.
        msg = f"Could not locate an income-statement page in {pdf.name} (text_layer={layer})"
        logger.warning(msg)
        return {"income_page": None, "text_layer": layer, "toc": toc,
                "resolution_error": msg, "route": "unresolved"}

    logger.info("Resolved pages for {}: income={} ({}), balance={} ({})",
                pdf.name, ip, ip_source, bsp, bsp_source)
    return {"income_page": ip, "bs_page": bsp,
            "income_page_source": ip_source, "bs_page_source": bsp_source,
            "text_layer": layer, "toc": toc, "route": "resolved"}

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
    """Compute ratios, Altman Z'', and the composite credit score. (Scoring.)"""
    stmt = state["statement"]
    ratios = compute_ratios(stmt)
    altman = compute_altman(stmt)
    composite = compute_composite(ratios, altman)
    credit = CreditReport(source_pdf=stmt.source_pdf, year=stmt.year_current,
                          ratios=ratios, altman=altman, composite=composite)
    return {"route": "scoring", "credit_report": credit}


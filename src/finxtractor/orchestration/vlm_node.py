"""Shared vision (VLM) node.

A first-class node in the pipeline graph that both the resolver and the extractor
escalate to when their text/OCR tiers can't do the job. It dispatches on
`vlm_task`:

  - 'locate'  : find the statement page(s) the resolver missed, then route on to
                the extractor (income located) or HITL (still missing).
  - 'extract' : read the statement table(s) the extractor's text tiers couldn't,
                merge into the running statement, then route to the validator.

The actual vision work lives in `agents.vlm_agent` (locate_with_vlm /
extract_with_vlm_agent); this node owns only the graph-level orchestration and
result merging.
"""
from pathlib import Path

from loguru import logger

from .state import PipelineState
from ..agents.vlm_agent import locate_with_vlm, extract_with_vlm_agent
from ..parsing.notes import resolve_line_item_notes
from ..normalize.normalize import normalize, merge, merge_raw


def vlm_node(state: PipelineState) -> dict:
    """Dispatch the queued vision task (set by the resolver or extractor)."""
    task = state.get("vlm_task")
    if task == "locate":
        return _locate(state)
    if task == "extract":
        return _extract(state)
    logger.warning("vlm_node reached with no/unknown task: {!r}", task)
    return {"route": "validate" if state.get("statement") is not None else "unresolved"}


def _locate(state: PipelineState) -> dict:
    """Locate the kinds the resolver flagged in `vlm_missing`, hinting each
    search with the other (already located) statement's page."""
    pdf = Path(state["pdf"])
    ip, bsp = state.get("income_page"), state.get("bs_page")
    ip_src, bsp_src = state.get("income_page_source"), state.get("bs_page_source")
    for kind in state.get("vlm_missing", []):
        hint = bsp if kind == "income" else ip
        page, source = locate_with_vlm(pdf, kind, hint_page=hint)
        if page is not None:
            if kind == "income":
                ip, ip_src = page, source
            else:
                bsp, bsp_src = page, source
    base = {"income_page": ip, "bs_page": bsp,
            "income_page_source": ip_src, "bs_page_source": bsp_src}
    if ip is None:
        msg = f"Could not locate an income-statement page in {pdf.name} (after VLM)"
        logger.warning(msg)
        return {**base, "route": "unresolved", "resolution_error": msg}
    logger.info("VLM located pages for {}: income={} ({}), balance={} ({})",
                pdf.name, ip, ip_src, bsp, bsp_src)
    return {**base, "route": "resolved"}


def _extract(state: PipelineState) -> dict:
    """Read each pending page with the vision model, normalize, and merge into
    the statement the extractor already assembled from text-readable pages."""
    pdf = Path(state["pdf"])
    pending = state.get("vlm_extract_pages", {})
    partial = state.get("statement")
    new: dict[str, object] = {}
    raws: list = []                          # VLM-read raw statements, for the explainability substrate
    for kind in ("income", "balance"):
        page = pending.get(kind)
        if page is None:
            continue
        raw = extract_with_vlm_agent(pdf, page)
        if raw is None:
            logger.warning("VLM extraction returned nothing for {} page {}", kind, page)
            continue
        resolve_line_item_notes(raw)
        raws.append(raw)
        new[kind] = normalize(raw)

    # Assemble income-first so its metadata wins; fold the text-extracted partial in.
    pieces = []
    if "income" in new:
        pieces.append(new["income"])
    if partial is not None:
        pieces.append(partial)
    if "balance" in new:
        pieces.append(new["balance"])
    if not pieces:
        msg = f"Extraction failed on all tiers (incl. VLM) for {pdf.name}"
        logger.warning(msg)
        return {"route": "unresolved", "resolution_error": msg}
    stmt = pieces[0]
    for p in pieces[1:]:
        stmt = merge(stmt, p)
    # Fold the VLM-read raws into the running raw statement (extractor seeded it).
    out = {"statement": stmt, "route": "validate"}
    raw_prev = state.get("raw_statement")
    if raws:
        out["raw_statement"] = merge_raw(*( ([raw_prev] if raw_prev else []) + raws ))
    return out

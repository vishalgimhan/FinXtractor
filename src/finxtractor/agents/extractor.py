"""Agentic statement extractor.

An LLM agent drives the per-page extraction ladder (TableFormer -> TableFormer
+OCR) and normalization via the tools in `tools/extractor.py`, deciding which
tier reads each page well and when to stop. A located page its text tiers can't
read is left unnormalized; the extractor then escalates that page to the shared
`vlm` graph node (task=extract), which reads it with the vision model.

Best-effort, like the resolver: if the LLM tier is unavailable it falls back to
the deterministic text+OCR ladder below. Either way `_finalize` is authoritative
— it auto-normalizes any usable raw the agent left behind, assembles the merged
statement, and decides whether vision extraction is still needed.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .prompts import extractor_system_prompt, extractor_user_prompt
from .tools.extractor import ExtractorContext, build_extractor_tools
from ..config import get_param
from ..parsing.docling_parser import parse_statement, table_confidence
from ..parsing.notes import resolve_line_item_notes
from ..normalize.normalize import normalize, merge


def extract(pdf: Path | str, income_page: int, bs_page: int | None = None,
            *, text_layer: str = "ok") -> dict:
    """Extract the located pages to one canonical statement. Returns a pipeline-
    state delta: `statement` (the merged canonical, possibly partial) plus a
    route — `validate` when done, or `vlm` (task=extract) when a page still needs
    the vision tier."""
    pages = {"income": income_page}
    if bs_page is not None:
        pages["balance"] = bs_page
    ctx = ExtractorContext(pdf=Path(pdf), text_layer=text_layer, pages=pages)
    try:
        _run_agent(ctx)
    except Exception as e:
        logger.warning("Extractor agent unavailable ({}); deterministic fallback",
                       type(e).__name__)
        _deterministic_extract(ctx)
    return _finalize(ctx)


def _run_agent(ctx: ExtractorContext) -> None:
    """Run the tool-calling agent. The artifact lives in `ctx` (the LLM can't
    emit a full statement), so no structured output is needed."""
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage
    from ..services.llm import get_chat_model

    agent = create_react_agent(
        get_chat_model(),
        build_extractor_tools(ctx),
        prompt=extractor_system_prompt(),
    )
    user = extractor_user_prompt(ctx.pages, ctx.text_layer)
    agent.invoke({"messages": [HumanMessage(user)]})


def _deterministic_extract(ctx: ExtractorContext) -> None:
    """Fallback text ladder: TableFormer (skip on a scan) then +OCR, per page,
    keeping the best raw. `_finalize` normalizes and escalates the rest."""
    for kind, page in ctx.pages.items():
        tiers = ([{}] if ctx.text_layer != "none" else []) + [{"ocr": True}]
        for kw in tiers:
            try:
                stmt = parse_statement(ctx.pdf, page, **kw)
            except Exception as e:
                logger.warning("Extraction tier {} failed on {} page {}: {}",
                               kw or "tableformer", kind, page, type(e).__name__)
                continue
            ctx.keep_best(kind, stmt, table_confidence(stmt))


def _finalize(ctx: ExtractorContext) -> dict:
    """Authoritative assembly: auto-normalize any usable raw the agent didn't,
    merge the canonicals, and escalate any page with no canonical to the vlm
    node. Income is the merge base so its metadata wins."""
    floor = get_param("vlm", "confidence_floor", default=0.0)
    for kind in ctx.pages:
        if kind not in ctx.canonical and kind in ctx.raw:
            raw = ctx.raw[kind]
            if raw.line_items and ctx.raw_conf.get(kind, 0.0) >= floor:
                resolve_line_item_notes(raw)
                ctx.canonical[kind] = normalize(raw)

    stmt = _assemble(ctx)
    pending = {k: ctx.pages[k] for k in ctx.pages if k not in ctx.canonical}
    if pending:
        logger.info("Extractor escalating to VLM node (extract): {}", list(pending))
        return {"statement": stmt, "route": "vlm",
                "vlm_task": "extract", "vlm_extract_pages": pending}
    return {"statement": stmt, "route": "validate"}


def _assemble(ctx: ExtractorContext):
    """Merge the available canonicals (income first, so its metadata wins)."""
    canons = [ctx.canonical[k] for k in ("income", "balance") if k in ctx.canonical]
    if not canons:
        return None
    stmt = canons[0]
    for c in canons[1:]:
        stmt = merge(stmt, c)
    return stmt

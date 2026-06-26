"""Agentic page resolver.

An LLM agent drives the statement-page-location tiers (extract -> triage ->
index lookup -> printed-TOC/heuristic -> OCR/VLM scan) via the tools in
`tools/resolver.py`, deciding which to call and when to stop. It returns a
structured result the resolver node turns into pipeline state.

Best-effort, like the TOC agent: if the LLM tier is unavailable (no provider/
lib, or an API error) it falls back to the deterministic cascade below, which is
the exact tiered logic the resolver used before it became agentic.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from .prompts import resolver_system_prompt, resolver_user_prompt
from .tools.resolver import ResolverContext, build_resolver_tools
from .page_locator import locate_scanned
from ..parsing.routing import resolve_page, INCOME_MARKERS, BALANCE_SHEET_MARKERS


class ResolverResult(BaseModel):
    """The agent's final answer: a page and the source tier for each kind."""
    income_page: int | None = Field(None, description="1-based income-statement page, or null")
    bs_page: int | None = Field(None, description="1-based balance-sheet page, or null")
    income_source: str | None = Field(None, description="tier that found income (e.g. 'agentic_toc', 'outline', 'heuristic', 'ocr_scan')")
    bs_source: str | None = Field(None, description="tier that found the balance sheet, or null")


def resolve(pdf: Path | str, income_override: int | None = None,
            bs_override: int | None = None) -> dict:
    """Resolve the income + balance pages for `pdf`. Returns a pipeline-state
    delta (the same keys the resolver node returned before): page numbers,
    sources, text_layer, page_index, route, and a resolution_error on a miss."""
    ctx = ResolverContext(pdf=Path(pdf))
    try:
        result = _run_agent(ctx, income_override, bs_override)
    except Exception as e:
        logger.warning("Resolver agent unavailable ({}); deterministic fallback",
                       type(e).__name__)
        return _deterministic_resolve(ctx, income_override, bs_override)
    return _finalize(ctx, result, income_override, bs_override)


def _run_agent(ctx: ResolverContext, income_override: int | None,
               bs_override: int | None) -> ResolverResult:
    """Run the tool-calling agent and return its structured answer."""
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage
    from ..services.llm import get_chat_model

    agent = create_react_agent(
        get_chat_model(),
        build_resolver_tools(ctx),
        prompt=resolver_system_prompt(),
        response_format=ResolverResult,
    )
    user = resolver_user_prompt(ctx.pdf.name, income_override, bs_override)
    out = agent.invoke({"messages": [HumanMessage(user)]})
    return out["structured_response"]


def _finalize(ctx: ResolverContext, result: ResolverResult,
              income_override: int | None, bs_override: int | None) -> dict:
    """Turn the agent's answer into a state delta. Overrides win authoritatively,
    pages are range-validated, and text_layer/page_index are guaranteed present
    for downstream nodes even if the agent never called those tools."""
    layer = ctx.ensure_text_layer()
    index = ctx.ensure_index()
    n = len(ctx.ensure_pages())

    def pick(override, page, source):
        if override is not None:
            return override, "override"
        if page is not None and 1 <= page <= n:
            return page, source
        return None, None

    ip, ip_source = pick(income_override, result.income_page, result.income_source)
    bsp, bsp_source = pick(bs_override, result.bs_page, result.bs_source)
    return _state(ctx, layer, index, ip, ip_source, bsp, bsp_source)


def _state(ctx: ResolverContext, layer, index, ip, ip_source, bsp, bsp_source) -> dict:
    """The resolver's state delta — resolved (route on) or unresolved (-> HITL)."""
    if ip is None:
        msg = f"Could not locate an income-statement page in {ctx.pdf.name} (text_layer={layer})"
        logger.warning(msg)
        return {"income_page": None, "text_layer": layer, "page_index": index,
                "resolution_error": msg, "route": "unresolved"}
    logger.info("Resolved pages for {}: income={} ({}), balance={} ({})",
                ctx.pdf.name, ip, ip_source, bsp, bsp_source)
    return {"income_page": ip, "bs_page": bsp,
            "income_page_source": ip_source, "bs_page_source": bsp_source,
            "text_layer": layer, "page_index": index, "route": "resolved"}


def _deterministic_resolve(ctx: ResolverContext, income_override: int | None,
                           bs_override: int | None) -> dict:
    """The original tiered cascade, kept as the fallback when the LLM tier is
    down: override -> unified index -> printed-TOC/heuristic -> OCR/VLM scan."""
    pdf = ctx.pdf
    pages = ctx.ensure_pages()
    layer = ctx.ensure_text_layer()
    index = ctx.ensure_index()
    logger.info("Triage for {}: text_layer={}", pdf.name, layer)

    def locate(override, markers):
        if override is not None:
            return override, "override"
        p, source = index.resolve(markers)
        if p is not None and 1 <= p <= len(pages):
            return p, source
        if layer != "none":               # printed-TOC + heuristic are pointless on a scan
            return resolve_page(pdf, pages, markers, outline=ctx.outline)
        return None, None

    ip, ip_source = locate(income_override, INCOME_MARKERS)
    bsp, bsp_source = locate(bs_override, BALANCE_SHEET_MARKERS)

    # Escalate to the scan locator when text tiers couldn't find income, or scanned.
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

    return _state(ctx, layer, index, ip, ip_source, bsp, bsp_source)

"""VLM locator tools — the vision tier as LLM-callable tools.

The VLM agent sees the PDF only through these tools: `page_count` to bound its
search and `scan_pages` to render-and-classify a page range with the vision
model. The range-scan keeps the agent's controller calls coarse (one per range,
not per page); a per-context budget caps the total vision calls so a long scan
can never sweep the whole document.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from langchain_core.tools import tool

from ...config import get_param
from ..page_locator import classify_page_vlm

# The statement kinds the vision model classifies a page into.
_KINDS = ["income", "balance"]


@dataclass
class VlmContext:
    """Shared state for one VLM-locator run: the PDF, its page count, and the
    vision-call budget (used spans every scan_pages call so the agent can't
    sweep the whole document across many small ranges)."""
    pdf: Path
    n_pages: int
    budget: int
    used: int = 0


def build_vlm_tools(ctx: VlmContext) -> list:
    """Build the VLM locator's tools, closed over `ctx`."""

    @tool
    def page_count() -> dict:
        """Total number of pages in the PDF (the upper bound for scan ranges)."""
        return {"n_pages": ctx.n_pages}

    @tool
    def scan_pages(kind: str, start: int, end: int) -> dict:
        """Render pages start..end (1-based, inclusive) and VLM-classify each,
        stopping at the first page that IS the `kind` statement ('income' or
        'balance'). Returns {found, page}. Keep ranges tight — each page is an
        expensive vision call, and a global budget limits the total."""
        if kind not in _KINDS:
            return {"error": f"kind must be one of {_KINDS}"}
        lo, hi = max(1, start), min(ctx.n_pages, end)
        for p in range(lo, hi + 1):
            if ctx.used >= ctx.budget:
                logger.info("VLM scan budget ({}) exhausted at page {}", ctx.budget, p)
                return {"found": False, "page": None, "budget_exhausted": True}
            ctx.used += 1
            if classify_page_vlm(ctx.pdf, p, _KINDS) == kind:
                logger.info("VLM agent located {} on page {}", kind, p)
                return {"found": True, "page": p}
        return {"found": False, "page": None}

    return [page_count, scan_pages]

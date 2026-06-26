"""Resolver tools — the statement-page-location tiers as LLM-callable tools.

Each tool wraps one deterministic function the old resolver node called in a
fixed `if` ladder (`extract_pages`, `assess_text_layer`, `build_page_index`,
the index/printed-TOC/heuristic lookups, the OCR/VLM scan). The agent now
decides which to call and when to stop.

The tools share one `ResolverContext`: `extract_pages`/`assess_text_layer`/
`build_page_index` populate it; the lookup tools read from it. Heavy data
(`pages`, the `PageIndex`) lives in the context, so tool results returned to the
model stay compact (a page number, a source string, a count). The lookup tools
lazily ensure their prerequisites, so an out-of-order call self-heals instead of
erroring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from langchain_core.tools import tool

from ...parsing.text import Page, extract_pages, assess_text_layer
from ...parsing.routing import (
    resolve_page, INCOME_MARKERS, BALANCE_SHEET_MARKERS,
)
from ...parsing.outline import PageIndex
from ...services.pdf_reader import get_pdf_reader
from ..toc import build_page_index
from ..page_locator import locate_scanned

# The two statement kinds the resolver locates, and the title markers for each.
_MARKERS: dict[str, list[str]] = {
    "income": INCOME_MARKERS,
    "balance": BALANCE_SHEET_MARKERS,
}


@dataclass
class ResolverContext:
    """Shared, in-memory state for one PDF's resolution run. Tools fill and read
    these fields; only the context (never the model) holds the page texts."""
    pdf: Path
    pages: list[Page] | None = None
    outline: list[tuple[int, str, int]] | None = None
    text_layer: str | None = None
    page_index: PageIndex | None = None

    # --- prerequisite helpers (also used by the lookup tools to self-heal) ---
    def ensure_pages(self) -> list[Page]:
        if self.pages is None:
            self.pages = extract_pages(self.pdf)
            self.outline = get_pdf_reader().outline(self.pdf)
        return self.pages

    def ensure_text_layer(self) -> str:
        if self.text_layer is None:
            self.text_layer = assess_text_layer(self.ensure_pages())
        return self.text_layer

    def ensure_index(self) -> PageIndex:
        if self.page_index is None:
            self.page_index = build_page_index(
                self.pdf, self.ensure_pages(), outline=self.outline)
        return self.page_index


def _hit(page: int | None, source: str | None, n_pages: int) -> dict:
    """Compact, validated tool result. A page outside 1..n_pages is rejected as
    a miss so a stray/hallucinated index never leaves the resolver."""
    if page is not None and 1 <= page <= n_pages:
        return {"found": True, "page": page, "source": source}
    return {"found": False, "page": None, "source": None}


def build_resolver_tools(ctx: ResolverContext) -> list:
    """Build the resolver's LLM tools, all closed over `ctx`. The factory keeps
    page texts and the index in the closure; the model sees only compact JSON."""

    @tool
    def extract_pages_tool() -> dict:
        """Read the PDF's page texts and embedded outline (bookmarks). Call this
        FIRST — every other tool needs the pages. Returns the page count and
        whether the PDF has an embedded outline."""
        pages = ctx.ensure_pages()
        return {"n_pages": len(pages), "has_outline": bool(ctx.outline)}

    @tool
    def assess_text_layer_tool() -> dict:
        """Classify the PDF's extractable text as 'ok', 'sparse', or 'none'
        (scanned). On 'none' the printed-TOC/heuristic tier is pointless — go
        straight to scan_pdf for any missing page. This value is also needed
        downstream, so call it once per run."""
        return {"text_layer": ctx.ensure_text_layer()}

    @tool
    def build_page_index_tool() -> dict:
        """Build the unified title->page index (agentic TOC over the printed
        'Contents' page + embedded outline). Call once before lookup_page_index.
        Returns the number of indexed entries."""
        index = ctx.ensure_index()
        return {"n_entries": len(index.entries)}

    @tool
    def lookup_page_index(kind: str) -> dict:
        """Resolve a statement page from the unified index (agentic TOC +
        outline) — the most reliable tier when present. `kind` is 'income' or
        'balance'. Returns {found, page, source} or a miss."""
        if kind not in _MARKERS:
            return {"error": f"kind must be one of {list(_MARKERS)}"}
        page, source = ctx.ensure_index().resolve(_MARKERS[kind])
        return _hit(page, source, len(ctx.ensure_pages()))

    @tool
    def lookup_printed_toc_and_heuristic(kind: str) -> dict:
        """Fallback for text PDFs: try the printed 'Contents' page, then a
        keyword/table heuristic over the page text. Skip this on a scanned PDF
        (text_layer == 'none'). `kind` is 'income' or 'balance'."""
        if kind not in _MARKERS:
            return {"error": f"kind must be one of {list(_MARKERS)}"}
        pages = ctx.ensure_pages()
        page, source = resolve_page(ctx.pdf, pages, _MARKERS[kind], outline=ctx.outline)
        return _hit(page, source, len(pages))

    @tool
    def scan_pdf(kind: str) -> dict:
        """Deepest tier for scanned/low-text PDFs: OCR pages, then VLM-classify
        the rest, early-stopping once found. Expensive — use only when the text
        tiers miss or text_layer == 'none'. `kind` is 'income' or 'balance'."""
        if kind not in _MARKERS:
            return {"error": f"kind must be one of {list(_MARKERS)}"}
        pages = ctx.ensure_pages()
        found = locate_scanned(ctx.pdf, len(pages), {kind: _MARKERS[kind]},
                               text_layer=ctx.ensure_text_layer())
        page, source = found.get(kind, (None, None))
        return _hit(page, source, len(pages))

    return [
        extract_pages_tool,
        assess_text_layer_tool,
        build_page_index_tool,
        lookup_page_index,
        lookup_printed_toc_and_heuristic,
        scan_pdf,
    ]

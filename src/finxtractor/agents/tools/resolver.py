"""Resolver tools — the statement-page-location tiers as LLM-callable tools.

Each tool wraps one deterministic function the old resolver node called in a
fixed `if` ladder (`extract_pages`, `assess_text_layer`, `build_page_index`,
the index/printed-TOC/heuristic lookups, the OCR scan). The vision tier is not a
tool here at all: when the text + OCR tiers still miss, the resolver escalates to
the shared `vlm` graph node (task=locate). The agent decides which of these tools
to call and when to stop.

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

    toc_page: int | None = None
    toc_text: str | None = None

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
    def locate_toc_page() -> dict:
        """Locate the Table of Contents (Contents) page number in the document.
        Uses fallback: native PDF text -> OCR (pages 1-10) -> VLM (pages 1-10).
        Returns the detected page number and the source, or a miss."""
        from ..toc import find_contents_page_with_fallback
        page, source, text = find_contents_page_with_fallback(
            ctx.pdf, ctx.ensure_pages(), ctx.ensure_text_layer())
        if page is not None:
            ctx.toc_page = page
            ctx.toc_text = text
            return {"found": True, "page": page, "source": source}
        return {"found": False, "page": None, "source": None}

    @tool
    def parse_contents_page(page: int) -> dict:
        """Parse the Table of Contents on the specified page using the LLM.
        This extracts structured page listings (titles and page numbers) and populates the page index.
        Returns the number of indexed entries, or an error if the page could not be parsed."""
        from ..toc import _structure_with_llm
        from ...parsing.outline import (
            printed_page_offset, LocatedEntry, entries_from_outline,
        )
        from ...services.ocr import ocr_page_text

        text = None
        if ctx.toc_page == page and ctx.toc_text:
            text = ctx.toc_text
        else:
            if ctx.ensure_text_layer() != "none":
                matched_pages = [p for p in ctx.ensure_pages() if p.number == page]
                if matched_pages:
                    text = matched_pages[0].text
            if not text:
                text = ocr_page_text(ctx.pdf, page)
                
        if not text or not text.strip():
            return {"error": f"No text found on page {page}"}
            
        entries = _structure_with_llm(text)
        if not entries:
            return {"error": f"LLM failed to parse contents on page {page}"}
            
        offset = printed_page_offset(ctx.ensure_pages()) or 0
        toc_entries = [
            LocatedEntry(title=e.title, page=e.page + offset, source="agentic_toc")
            for e in entries
        ]
        # Merge with the embedded outline (bookmarks) only — NOT ensure_index(),
        # which would re-run the agentic TOC parse over a freshly re-detected
        # (native-text-only) contents page and duplicate these entries. Agentic
        # entries first so they win on a marker tie (mirrors build_page_index).
        outline = (ctx.outline if ctx.outline is not None
                   else get_pdf_reader().outline(ctx.pdf))
        ctx.page_index = PageIndex(entries=toc_entries + entries_from_outline(outline))
        return {"n_entries": len(ctx.page_index.entries), "offset": offset}

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
    def ocr_scan(kind: str) -> dict:
        """OCR-scan the pages and lock a page for `kind` only on a strong text
        match (marker + a year + several money figures). Cheaper than the vision
        agent — try this before consult_vlm_agent on a scan. 'income'/'balance'."""
        if kind not in _MARKERS:
            return {"error": f"kind must be one of {list(_MARKERS)}"}
        pages = ctx.ensure_pages()
        found = locate_scanned(ctx.pdf, len(pages), {kind: _MARKERS[kind]},
                               text_layer=ctx.ensure_text_layer(), use_vlm=False)
        page, source = found.get(kind, (None, None))
        return _hit(page, source, len(pages))

    return [
        extract_pages_tool,
        assess_text_layer_tool,
        locate_toc_page,
        parse_contents_page,
        lookup_page_index,
        lookup_printed_toc_and_heuristic,
        ocr_scan,
    ]

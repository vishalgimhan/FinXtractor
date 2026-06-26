"""Agentic table-of-contents parser.

Turns a report's printed 'Contents' page into a structured, reusable object via
the LLM. It is best-effort: if the LLM tier is unavailable (no provider/lib, or
an API error) it returns None and the caller falls back to the deterministic
TOC logic in parsing/outline.py.

The result resolves any statement page (income, balance, notes, ...) from one
parse; the resolver builds it once and carries it in pipeline state.
"""
from __future__ import annotations

from loguru import logger
from pydantic import BaseModel, Field

from pathlib import Path

from ..parsing.text import Page
from ..parsing.outline import (
    find_contents_page, printed_page_offset, entries_from_outline,
    LocatedEntry, PageIndex,
)
from ..services.pdf_reader import get_pdf_reader
from .prompts import toc_extraction_prompt


class TocEntry(BaseModel):
    title: str
    page: int                       # printed page number, as listed in the contents


class _TocReply(BaseModel):
    """What the LLM fills (entries only; the offset is computed deterministically)."""
    entries: list[TocEntry] = Field(default_factory=list)


class StructuredToc(BaseModel):
    """Structured contents page. physical page = entry.page + page_offset."""
    entries: list[TocEntry] = Field(default_factory=list)
    page_offset: int = 0

    def resolve(self, markers: list[str]) -> int | None:
        """First entry whose title matches any marker -> its physical page."""
        low = [m.lower() for m in markers]
        for e in self.entries:
            title = e.title.lower()
            if any(m in title for m in low):
                return e.page + self.page_offset
        return None


def _structure_with_llm(toc_text: str) -> list[TocEntry] | None:
    """Structure the contents text via the LLM, or None if the tier is down."""
    try:
        from ..services.llm import get_chat_model     # lazy: keeps import langchain-free
        model = get_chat_model().with_structured_output(_TocReply)
        reply: _TocReply = model.invoke(toc_extraction_prompt(toc_text))
        return reply.entries or None
    except Exception as e:
        logger.warning("TOC agent unavailable ({}); using deterministic fallback",
                       type(e).__name__)
        return None


def get_structured_toc(pages: list[Page]) -> StructuredToc | None:
    """Agentic structured TOC from already-extracted `pages`, or None if there's
    no contents page / the LLM tier is unavailable. The caller (resolver) holds
    the result in state, so this does no caching or PDF reading itself."""
    contents = find_contents_page(pages)
    if contents is None:
        logger.debug("No printed contents page; TOC agent skipped")
        return None
    entries = _structure_with_llm(contents.text)
    if not entries:
        return None
    offset = printed_page_offset(pages) or 0
    logger.info("Structured TOC via agent: {} entries, offset {}", len(entries), offset)
    return StructuredToc(entries=entries, page_offset=offset)


def _agentic_entries(pages: list[Page]) -> list[LocatedEntry]:
    """Agentic TOC entries as physical-page index entries, or [] if unavailable."""
    toc = get_structured_toc(pages)
    if toc is None:
        return []
    return [LocatedEntry(title=e.title, page=e.page + toc.page_offset, source="agentic_toc")
            for e in toc.entries]


def build_page_index(pdf: Path | str, pages: list[Page], *,
                     outline: list[tuple[int, str, int]] | None = None) -> PageIndex:
    """Unify the two title->page sources into one index: agentic TOC first
    (printed contents page, via the LLM), then the embedded outline (bookmarks).
    Agentic entries are listed first so they win on a marker tie, preserving the
    resolver's historical precedence. Either source may be empty (no contents
    page / LLM down / no bookmarks); the deterministic printed-TOC and heuristic
    tiers remain the resolver's lower fallback."""
    if outline is None:
        outline = get_pdf_reader().outline(pdf)
    entries = _agentic_entries(pages) + entries_from_outline(outline)
    logger.info("Page index for {}: {} entr(ies)", Path(pdf).name, len(entries))
    return PageIndex(entries=entries)


def classify_page_is_toc(pdf: Path | str, page: int) -> bool:
    """Render one page and ask the vision model if it is a Contents / Table of Contents page."""
    try:
        import base64
        from langchain_core.messages import HumanMessage
        from ..services.vlm import get_vlm_model
        from ..services.pdf_reader import get_pdf_reader
        
        class _IsToc(BaseModel):
            is_toc: bool
            
        model = get_vlm_model().with_structured_output(_IsToc)
        b64 = base64.b64encode(get_pdf_reader().render_page(pdf, page)).decode()
        prompt = (
            "You are shown ONE page of a financial report as an image. Decide if this page "
            "is the Table of Contents, Contents, or Index page of the report. "
            "Return true if it lists sections/chapters/pages of the document, and false otherwise."
        )
        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ])
        result = model.invoke([message])
        return result.is_toc
    except Exception as e:
        logger.warning("VLM TOC classify failed on page {}: {}", page, type(e).__name__)
        return False


def find_contents_page_with_fallback(
    pdf: Path | str, pages: list[Page], text_layer: str
) -> tuple[int | None, str | None, str | None]:
    """Locate the Contents page, its source, and its text content.
    Fallback: Native text -> OCR (pages 1-10) -> VLM (pages 1-10)."""
    # 1. Native text (if available)
    if text_layer != "none":
        contents_page = find_contents_page(pages)
        if contents_page is not None:
            logger.info("Located Contents page on page {} via native text", contents_page.number)
            return contents_page.number, "native_text", contents_page.text

    # 2. OCR (pages 1-10)
    logger.debug("TOC not found via native text; trying OCR fallback on pages 1-10")
    from ..services.ocr import ocr_page_text
    limit = min(len(pages), 10)
    for i in range(1, limit + 1):
        text = ocr_page_text(pdf, i)
        low = text.lower()
        if "table of contents" in low or ("contents" in low and "page" in low):
            logger.info("Located Contents page on page {} via OCR", i)
            return i, "ocr", text

    # 3. VLM (pages 1-10)
    logger.debug("TOC not found via OCR; trying VLM fallback on pages 1-10")
    for i in range(1, limit + 1):
        if classify_page_is_toc(pdf, i):
            logger.info("Located Contents page on page {} via VLM", i)
            text = ocr_page_text(pdf, i)
            return i, "vlm", text

    return None, None, None

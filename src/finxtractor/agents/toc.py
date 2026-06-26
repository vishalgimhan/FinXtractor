"""Agentic table-of-contents parser.

Turns a report's printed 'Contents' page into a structured, reusable object via
the LLM. It is best-effort: if the LLM tier is unavailable (no provider/lib, or
an API error) it returns None and the caller falls back to the deterministic
TOC logic in parsing/outline.py.

The result resolves any statement page (income, balance, notes, ...) from one
parse, and is cached so it is computed only once per file.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from ..parsing.text import extract_pages
from ..parsing.outline import find_contents_page, printed_page_offset
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


@lru_cache(maxsize=8)
def _build(path: str, _mtime: float) -> StructuredToc | None:
    pages = extract_pages(path)
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


def get_structured_toc(pdf: Path | str) -> StructuredToc | None:
    """Agentic structured TOC for `pdf`, or None if unavailable. Cached per
    file (keyed by path + mtime) so it is built at most once."""
    p = Path(pdf)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = 0.0
    return _build(str(p), mtime)

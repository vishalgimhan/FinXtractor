from pathlib import Path

from loguru import logger

from ..config import get_markers, get_pattern
from .text import Page
# TOC/outline logic lives in outline.py; re-exported here for back-compat.
from .outline import (
    INCOME_MARKERS,
    _matches,
    find_from_toc,
    page_from_outline,
    page_from_printed_toc,
    note_pages_from_toc,
    _find_contents_page,
)

BALANCE_SHEET_MARKERS = get_markers("balance_sheet")
NOTES_MARKERS = get_markers("notes")

_YEAR = get_pattern("year")
_NUMBER = get_pattern("number")


def find_income_pages(pages: list[Page]) -> list[int]:
    matches = [p.number for p in pages if _matches(p.text, INCOME_MARKERS)]
    logger.debug("Income-page keyword hits: {}", matches)
    return matches


def find_notes_pages(pages: list[Page]) -> list[int]:
    matches = [p.number for p in pages if _matches(p.text, NOTES_MARKERS)]
    logger.debug("Notes-page keyword hits: {}", matches)
    return matches


def rank_pages(pages: list[Page], markers: list[str]) -> list[int]:
    """Pages matching `markers`, best-first: prefer pages that also look like a
    real table (has a year and many numeric tokens) to filter out TOC/auditor
    mentions."""
    scored = []
    for p in pages:
        if not _matches(p.text, markers):
            continue
        score = (1 if _YEAR.search(p.text) else 0, len(_NUMBER.findall(p.text)))
        scored.append((score, p.number))
    scored.sort(reverse=True)
    ranked = [num for _, num in scored]
    logger.debug("Ranked pages for {} markers: {}", len(markers), ranked)
    return ranked


def resolve_page(pdf: Path, pages: list[Page], markers: list[str]) -> tuple[int | None, str | None]:
    """Locate a statement page matching `markers`, best source first:
    embedded outline -> printed contents page -> keyword heuristic.
    Returns (1-based page, source) or (None, None)."""
    logger.info("Resolving page for {}", pdf.name)
    page, source = find_from_toc(pdf, pages, markers)
    if page is not None:
        return page, source
    ranked = rank_pages(pages, markers)
    if ranked:
        logger.info("Resolved page {} from heuristic for {}", ranked[0], pdf.name)
        return ranked[0], "heuristic"
    logger.warning("Could not resolve a page for {}", pdf.name)
    return None, None

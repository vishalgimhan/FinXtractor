from pathlib import Path

from loguru import logger

from ..config import get_markers, get_pattern
from .text import Page
# TOC/outline logic lives in outline.py. `_matches`/`find_from_toc` are used here;
# `note_pages_from_toc` is re-exported for note_tables.py.
from .outline import _matches, find_from_toc, note_pages_from_toc

# What an income-statement title looks like (in an outline entry or TOC line).
INCOME_MARKERS = get_markers("income")
BALANCE_SHEET_MARKERS = get_markers("balance_sheet")
NOTES_MARKERS = get_markers("notes")

_YEAR = get_pattern("year")
_NUMBER = get_pattern("number")


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


def resolve_page(pdf: Path, pages: list[Page], markers: list[str],
                 outline: list[tuple[int, str, int]] | None = None) -> tuple[int | None, str | None]:
    """Locate a statement page matching `markers`, best source first:
    embedded outline -> printed contents page -> keyword heuristic.
    Returns (1-based page, source) or (None, None). Pass `outline` (already read)
    to avoid re-opening the PDF for the bookmarks on every call."""
    logger.info("Resolving page for {}", pdf.name)
    page, source = find_from_toc(pdf, pages, markers, outline=outline)
    if page is not None:
        return page, source
    ranked = rank_pages(pages, markers)
    if ranked:
        logger.info("Resolved page {} from heuristic for {}", ranked[0], pdf.name)
        return ranked[0], "heuristic"
    logger.warning("Could not resolve a page for {}", pdf.name)
    return None, None

"""Table-of-contents / outline based page location.

Two mechanisms, best-first: the PDF's embedded outline (bookmarks), then a
printed 'Contents' page (mapping printed page numbers to physical indices via a
detected offset). Also resolves note numbers to their physical pages.
"""
from collections import Counter
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from ..config import get_markers, get_pattern
from ..services.pdf_reader import get_pdf_reader
from .text import Page



# A line that is nothing but a small integer (a printed page number, not a year).
_STANDALONE_INT = get_pattern("standalone_int")


def _matches(text: str, markers: list[str]) -> bool:
    low = text.lower()
    return any(m in low for m in markers)


# --- unified title -> physical-page index -----------------------------------

class LocatedEntry(BaseModel):
    title: str
    page: int                       # 1-based physical page
    source: str                     # "agentic_toc" | "outline"


class PageIndex(BaseModel):
    """One title->physical-page map, merged from every location source (embedded
    outline + agentic TOC). Entries are pre-ordered by source priority, so the
    first marker match wins. Built once and carried in pipeline state."""
    entries: list[LocatedEntry] = Field(default_factory=list)

    def resolve(self, markers: list[str]) -> tuple[int | None, str | None]:
        """First entry whose title matches any marker -> (physical page, source)."""
        low = [m.lower() for m in markers]
        for e in self.entries:
            if any(m in e.title.lower() for m in low):
                return e.page, e.source
        return None, None


def entries_from_outline(
    outline: list[tuple[int, str, int]]
) -> list[LocatedEntry]:
    """Embedded-outline bookmarks as index entries (titles already physical)."""
    return [LocatedEntry(title=title, page=page, source="outline")
            for _level, title, page in outline if page >= 1]


# --- embedded outline -------------------------------------------------------

def page_from_outline(pdf: Path, markers: list[str],
                      outline: list[tuple[int, str, int]] | None = None) -> int | None:
    """Use the PDF's embedded outline/bookmarks (most reliable when present).

    Returns the 1-based physical page of the first entry whose title matches
    `markers`, or None if the PDF has no outline or no matching entry. Pass
    `outline` (already read by the caller) to avoid re-opening the PDF.
    """
    toc = outline if outline is not None else get_pdf_reader().outline(pdf)
    logger.debug("Checking outline for a matching page in {}", pdf.name)
    for _level, title, page in toc:
        if page >= 1 and _matches(title, markers):
            logger.info("Resolved page {} from outline in {}", page, pdf.name)
            return page
    return None


# --- printed 'Contents' page ------------------------------------------------

def _find_contents_page(pages: list[Page]) -> Page | None:
    for p in pages:
        low = p.text.lower()
        if "table of contents" in low or ("contents" in low and "page" in low):
            return p
    return None


def _printed_toc_entry_page(text: str, markers: list[str]) -> int | None:
    """In a printed contents listing, find the page number that follows the
    first line matching one of the markers."""
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if line and _matches(line, markers):
            for nxt in lines[i + 1:]:
                m = _STANDALONE_INT.match(nxt)
                if m:
                    return int(m.group(1))
    return None


def _printed_page_number(text: str) -> int | None:
    """Best guess of a page's *printed* page number: the last standalone
    small-integer line (typically the footer)."""
    candidate = None
    for line in text.splitlines():
        m = _STANDALONE_INT.match(line)
        if m:
            candidate = int(m.group(1))
    return candidate


def _page_offset(pages: list[Page], contents: Page | None) -> int | None:
    """Offset between physical PDF page index and printed page number, taken as
    the most common (physical - printed) across pages. The contents page is
    skipped because its listing is full of stray page numbers."""
    offsets: Counter[int] = Counter()
    for p in pages:
        if contents is not None and p.number == contents.number:
            continue
        printed = _printed_page_number(p.text)
        if printed is not None and 0 < printed <= len(pages):
            offsets[p.number - printed] += 1
    if not offsets:
        return None
    return offsets.most_common(1)[0][0]


def find_contents_page(pages: list[Page]) -> Page | None:
    """Public: the printed 'Contents' page, if the report has one."""
    return _find_contents_page(pages)


def printed_page_offset(pages: list[Page]) -> int | None:
    """Public: offset between physical index and printed page number
    (physical = printed + offset), inferred from page footers."""
    return _page_offset(pages, _find_contents_page(pages))


def page_from_printed_toc(pages: list[Page], markers: list[str]) -> int | None:
    """Parse a printed 'Contents' page, find the entry matching `markers`, then
    map its listed (printed) page number to a physical PDF page index.
    Returns 1-based physical page or None."""
    contents = _find_contents_page(pages)
    if contents is None:
        logger.debug("No printed contents page found")
        return None
    printed_target = _printed_toc_entry_page(contents.text, markers)
    if printed_target is None:
        logger.debug("Printed contents page did not list a matching entry")
        return None
    offset = _page_offset(pages, contents)
    if offset is None:
        logger.debug("Could not infer printed-page offset from contents page")
        return None
    physical = printed_target + offset
    if 1 <= physical <= len(pages):
        logger.info("Resolved page {} from printed TOC", physical)
        return physical
    return None


def _toc_note_listing(contents_text: str) -> dict[int, int]:
    """Parse the notes listing in a printed contents page into
    {note_number: printed_page}. The listing repeats number / title / page
    triples; section group headers (non-numeric lines) are ignored.

    Parsing starts after the 'Notes to ... financial statements' header so the
    primary-statement page numbers above it don't collide with note numbers."""
    lines = [ln.strip() for ln in contents_text.splitlines()]
    start = 0
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "notes to" in low and "financial statements" in low:
            start = i + 1
    listing: dict[int, int] = {}
    current: int | None = None
    expecting_page = False
    for ln in lines[start:]:
        m = _STANDALONE_INT.match(ln)
        if not m:
            continue                      # title / section-header line
        val = int(m.group(1))
        if expecting_page:
            if current is not None and current not in listing:
                listing[current] = val    # this int is the printed page
            current, expecting_page = None, False
        else:
            current, expecting_page = val, True  # this int is the note number
    return listing


def note_pages_from_toc(pages: list[Page], numbers: list[int]) -> dict[int, int]:
    """Map each requested note number -> 1-based physical page, using the printed
    contents listing plus the printed->physical offset. Only resolvable notes
    are returned."""
    contents = _find_contents_page(pages)
    if contents is None:
        logger.debug("No printed contents page found for note lookup")
        return {}
    listing = _toc_note_listing(contents.text)
    offset = _page_offset(pages, contents)
    if offset is None:
        logger.debug("Could not infer printed-page offset for note lookup")
        return {}
    located: dict[int, int] = {}
    for n in numbers:
        printed = listing.get(n)
        if printed is None:
            continue
        physical = printed + offset
        if 1 <= physical <= len(pages):
            located[n] = physical
    logger.info("Resolved note pages from TOC: {}", located)
    return located


# --- unified entry point ----------------------------------------------------

def find_from_toc(pdf: Path, pages: list[Page], markers: list[str],
                  outline: list[tuple[int, str, int]] | None = None) -> tuple[int | None, str | None]:
    """Locate a statement page via TOC for the given `markers`, best source first:
    embedded outline -> printed contents page. Returns (page, source) or (None, None).
    Pass `outline` (already read) to avoid re-opening the PDF for the bookmarks."""
    page = page_from_outline(pdf, markers, outline=outline)
    if page is not None:
        return page, "outline"
    page = page_from_printed_toc(pages, markers)
    if page is not None:
        return page, "printed_toc"
    return None, None

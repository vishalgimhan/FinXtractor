from pathlib import Path

from loguru import logger

from .text import extract_pages
from .routing import note_pages_from_toc
from .docling_parser import _money_cells, _clean

from ..schemas import Statement
from ..config import get_param
from ..services.table_extractor import get_table_extractor


def locate_notes(pdf: Path | str, numbers: list[int]) -> dict[int, int]:
    """Map each note number -> its 1-based physical page via the printed
    contents page (number -> printed page -> physical, offset-resolved)."""
    pages = extract_pages(pdf)
    return note_pages_from_toc(pages, numbers)


def _densest_rows(pdf: Path | str, page_number: int, *, do_ocr: bool | None) -> tuple[list[list[str]], int]:
    """Densest table on a page as cleaned rows, plus its money-cell count (the
    same density proxy `parse_statement` ranks statement tables by)."""
    tables = get_table_extractor(do_ocr=do_ocr).extract_tables(pdf, page_number)
    if not tables:
        return [], 0
    best = max(tables, key=lambda pt: _money_cells(pt.df))
    rows = [_clean(row) for row in best.df.to_numpy().tolist()]
    return rows, _money_cells(best.df)


def _vlm_rows(pdf: Path | str, page_number: int) -> list[list[str]]:
    """Read a note page with the VLM and flatten its line items into rows."""
    try:
        from ..services.vlm import extract_with_vlm
        stmt = extract_with_vlm(pdf, page_number)
    except Exception as exc:                            # model offline / call failed
        logger.warning("VLM note extraction failed on page {}: {}", page_number, type(exc).__name__)
        return []
    rows = [["Description", "Current", "Prior"]]
    for li in stmt.line_items:
        rows.append([
            li.label_raw,
            "" if li.value_current is None else str(li.value_current),
            "" if li.value_prior is None else str(li.value_prior),
        ])
    return rows if len(rows) > 1 else []


def extract_note_table(pdf: Path | str, page_number: int, *, use_vlm: bool = True
                       ) -> tuple[list[list[str]], str | None]:
    """Densest table on a note's page, escalating like the statement ladder:
    TableFormer (text) -> TableFormer+OCR -> VLM. Keeps the densest result above
    the money-cell floor; returns (rows, tier) where tier names the tier that won
    (or None if nothing was found)."""
    floor = int(get_param("notes", "min_money_cells", default=3))

    rows, score = _densest_rows(pdf, page_number, do_ocr=None)
    tier = "tableformer" if rows else None

    if score < floor:                                   # weak text parse -> try OCR
        ocr_rows, ocr_score = _densest_rows(pdf, page_number, do_ocr=True)
        if ocr_score > score:
            rows, score, tier = ocr_rows, ocr_score, "tableformer_ocr"

    if score < floor and use_vlm:                       # still weak -> vision fallback
        vlm_rows = _vlm_rows(pdf, page_number)
        if vlm_rows:
            rows, tier = vlm_rows, "vlm"

    return rows, tier


def collect_note_tables(stmt: Statement, pdf: Path | str, *, use_vlm: bool = True) -> dict[int, dict]:
    """For every note cited in the statement, locate and extract its table via
    the escalating ladder, and record which line items reference it (for the
    dashboard's bidirectional note<->account links)."""
    referenced_by: dict[int, list[str]] = {}
    for item in stmt.line_items:
        for ref in item.note_refs:
            referenced_by.setdefault(ref.number, [])
            if item.label_raw not in referenced_by[ref.number]:
                referenced_by[ref.number].append(item.label_raw)

    numbers = sorted(referenced_by)
    located = locate_notes(pdf, numbers)
    notes: dict[int, dict] = {}
    for n in numbers:
        page = located.get(n)
        rows, tier = extract_note_table(pdf, page, use_vlm=use_vlm) if page else ([], None)
        notes[n] = {
            "number": n,
            "page": page,
            "rows": rows,
            "found": page is not None and bool(rows),
            "tier": tier,
            "referenced_by": referenced_by[n],
        }
        logger.debug("Note {}: page={} tier={} rows={} refs={}",
                     n, page, tier, len(rows), len(referenced_by[n]))
    return notes

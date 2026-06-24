from pathlib import Path
from .text import extract_pages
from .routing import note_pages_from_toc

from ..schemas import Statement
from .docling_parser import _build_converter, _numeric_density

def locate_notes(pdf: Path | str, numbers: list[int]) -> dict[int, int]:
    """Map each note number -> its 1-based physical page via the printed
    contents page (number -> printed page -> physical, offset-resolved)."""
    pages = extract_pages(pdf)
    return note_pages_from_toc(pages, numbers)

def extract_note_table(pdf: Path | str, page_number: int) -> list[list[str]]:
    """Densest table on the note's page, as raw rows. Empty list if none."""
    result = _build_converter().convert(str(pdf), page_range=(page_number, page_number))
    tables = result.document.tables
    if not tables:
        return []
    table = max(tables, key=_numeric_density)
    df = table.export_to_dataframe()
    return [[("" if str(c).strip().lower() == "nan" else str(c).strip())
             for c in row] for row in df.to_numpy().tolist()]

def collect_note_tables(stmt: Statement, pdf: Path | str) -> dict[int, dict]:
    """For every note cited in the statement, locate and extract its table."""
    numbers = sorted({ref.number for item in stmt.line_items
                      for ref in item.note_refs})
    located = locate_notes(pdf, numbers)
    notes: dict[int, dict] = {}
    for n in numbers:
        page = located.get(n)
        notes[n] = {
            "number": n,
            "page": page,
            "rows": extract_note_table(pdf, page) if page else [],
            "found": page is not None,
        }
    return notes
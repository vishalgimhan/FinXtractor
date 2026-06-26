import re
from pathlib import Path

from loguru import logger

from ..schemas import LineItem, Statement, Provenance
from ..services.table_extractor import ParsedTable, get_table_extractor
from .units import detect_units, detect_currency, detect_sign_convention
from .text import extract_pages

# Strict money cell: thousands-grouped (optional decimal), 3+ digit integer
# (optional decimal), or a plain decimal; parens = negative. A bare 1-2 digit
# integer is NOT money (those are note numbers).
_MONEY = re.compile(
    r"^\(?\$?\s?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{3,}(?:\.\d+)?|\d+\.\d+)\)?$"
)
# Note reference: a small integer, optionally with a letter sub-part, as a
# comma-list, e.g. "4", "26", "3(a)", "3a", "5, 6", "3(a), 3(b)".
_NOTE = re.compile(r"^\d{1,2}(?:\([a-z]\)|[a-z])?(?:\s*,\s*\d{1,2}(?:\([a-z]\)|[a-z])?)*$", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
# Caption/title rows to drop. Kept narrow: "for the year" alone would also
# swallow real subtotals like "Total comprehensive loss for the year ...".
_SKIP = ("year ended", "annual report")
# Labels of total/subtotal rows. "total" plus the profit/loss result lines that
# are subtotals even though they don't say "total".
_SUBTOTAL_MARKERS = (
    "total",
    "net profit",
    "net loss",
    "net income",
    "profit before",
    "loss before",
    "profit after",
    "loss after",
    "profit for the",
    "loss for the",
    "profit/(loss)",
    "(loss)/profit",
    "total comprehensive",
)

def table_confidence(stmt: Statement) -> float:
    """Cheap proxy for 'did TableFormer parse cleanly?' — 0.0 to 1.0."""
    items = stmt.line_items
    if not items:
        return 0.0
    have_two = sum(1 for i in items if i.value_prior is not None)
    have_label = sum(1 for i in items if len(i.label_raw) > 2)
    return min(len(items) / 8, 1.0) * 0.4 \
        + (have_two / len(items)) * 0.3 \
        + (have_label / len(items)) * 0.3

# DataFrame export uses NaN for empty cells
def _clean(cells: list) -> list[str]:
    out = []
    for c in cells:
        s = str(c).strip()
        out.append("" if s.lower() == "nan" else s)
    return out

# money strings to numerical
def _to_float(token: str) -> float:
    neg = "(" in token
    digits = re.sub(r"[(),$\s]", "", token)
    return -float(digits) if neg else float(digits)

# to identify page with right table (dense -> more likely)
def _money_cells(df) -> int:
    flat = df.astype(str).to_numpy().ravel()
    return sum(1 for c in flat if _MONEY.match(str(c).strip()))

# detect years
def _detect_years(df) -> tuple[int | None, int | None]:
    blob = " ".join(str(x) for x in df.columns) + " " + \
            " ".join(df.astype(str).to_numpy().ravel().tolist())
    years = sorted({int(y) for y in _YEAR.findall(blob)}, reverse=True)
    return (years[0] if years else None, years[1] if len(years) > 1 else None)

ColumnRoles = tuple[list[int], int | None, list[int]]


def _column_roles(df) -> ColumnRoles:
    """Classify dataframe columns by their header into:
    value columns (year-bearing, current-first), the note column, and label
    columns. Returns ([] , None, []) when no year header is found."""
    value_cols: list[tuple[int, int]] = []
    note_col: int | None = None
    label_cols: list[int] = []
    for idx, name in enumerate(df.columns):
        s = str(name)
        ym = _YEAR.search(s)
        if ym:
            value_cols.append((idx, int(ym.group())))
        elif "note" in s.lower():
            note_col = idx
        else:
            label_cols.append(idx)
    value_cols.sort(key=lambda t: t[1], reverse=True)  # current year first
    return [i for i, _ in value_cols], note_col, label_cols


def _make_item(label: str, vals: list[float | None], note_raw: str | None) -> LineItem:
    low = label.lower()
    return LineItem(
        label_raw=label,
        value_current=vals[0] if len(vals) > 0 else None,
        value_prior=vals[1] if len(vals) > 1 else None,
        note_ref_raw=note_raw,
        is_subtotal=any(m in low for m in _SUBTOTAL_MARKERS),
    )


def _row_to_item(cells: list[str], roles: ColumnRoles) -> LineItem | None:
    """Column-aware row parser. Reads values from the known year columns, so a
    nil dash ('-') keeps the remaining figure in its correct year column.
    Falls back to positional parsing when headers carry no year."""
    value_cols, note_col, label_cols = roles
    if not value_cols:
        return _row_to_item_positional(cells)

    cells = _clean(cells)
    if any(s in " ".join(cells).lower() for s in _SKIP):
        return None

    vals = [
        _to_float(cells[i]) if i < len(cells) and _MONEY.match(cells[i]) else None
        for i in value_cols[:2]
    ]
    if all(v is None for v in vals):
        return None  # section header / blank row

    note_raw = None
    if note_col is not None and note_col < len(cells):
        c = cells[note_col]
        if c and _NOTE.match(c):
            note_raw = c

    label = " ".join(cells[i] for i in label_cols if i < len(cells) and cells[i]).strip()
    if not label:
        return None
    return _make_item(label, vals, note_raw)


def _row_to_item_positional(cells: list[str]) -> LineItem | None:
    """Fallback when the table has no year-bearing headers: take the rightmost
    two money cells as the value columns."""
    cells = _clean(cells)
    if any(s in " ".join(cells).lower() for s in _SKIP):
        return None

    money_idx = [i for i, c in enumerate(cells) if _MONEY.match(c)]
    if not money_idx:
        return None  # section header / blank row

    value_idx = money_idx[-2:]                       # rightmost two = year columns
    vals = [_to_float(cells[i]) for i in value_idx]

    note_raw, label_parts = None, []
    for i, c in enumerate(cells):
        if i in value_idx or not c:
            continue
        if note_raw is None and i != 0 and _NOTE.match(c):
            note_raw = c                             # note column sits left of values
        elif not _MONEY.match(c):
            label_parts.append(c)

    label = " ".join(label_parts).strip()
    if not label:
        return None
    return _make_item(label, vals, note_raw)

def _table_to_items(pt: ParsedTable, page_number: int, roles: ColumnRoles) -> list[LineItem]:
    """Parse one extracted table's rows into LineItems with provenance.
    `roles` is precomputed by the caller from `pt.df`."""
    prov_bbox = pt.bbox                               # four floats or None, per schema
    df = pt.df
    items: list[LineItem] = []
    for _, row in df.iterrows():
        cells = row.tolist()
        item = _row_to_item(cells, roles)
        if item:
            item.page = page_number
            item.provenance = Provenance(
                page=page_number, bbox=prov_bbox,
                raw_cell_text=" | ".join(c for c in _clean(cells) if c),
            )
            items.append(item)
    return items


def _apply_context(stmt: Statement, pdf_path: Path, page_number: int, df) -> None:
    """Fill years (from the table) and units/currency/sign (from the page text)."""
    stmt.year_current, stmt.year_prior = _detect_years(df)
    page_text = next((p.text for p in extract_pages(pdf_path) if p.number == page_number), "")
    stmt.units = detect_units(page_text)
    stmt.currency = detect_currency(page_text)
    stmt.sign_convention = detect_sign_convention(page_text)
    logger.info(
        "Detected context for {} page {}: year_current={}, year_prior={}, units={}, currency={}, sign_convention={}",
        pdf_path.name, page_number, stmt.year_current, stmt.year_prior,
        stmt.units, stmt.currency, stmt.sign_convention,
    )


def _has_year_columns(roles: ColumnRoles) -> bool:
    """A statement table: its header carries at least one year-bearing column."""
    value_cols, _note, _label = roles
    return bool(value_cols)


def parse_statement(pdf: Path | str, page_number: int, *, ocr: bool = False) -> Statement:
    """Parse a page into a Statement, aggregating every table whose header carries
    a year column (so multi-table statements are captured without ingesting
    unrelated tables). Falls back to the densest table when no table has a year
    header (positional parsing). Context comes from the densest selected table.

    ocr=True runs TableFormer with OCR on (for scanned pages with no text layer)."""
    pdf_path = Path(pdf)
    logger.info("Parsing {} page {} (ocr={})", pdf_path.name, page_number, ocr)
    tables = get_table_extractor(do_ocr=True if ocr else None).extract_tables(pdf, page_number)
    stmt = Statement(source_pdf=pdf_path.name, statement_pages=[page_number])
    if not tables:
        logger.warning("No tables found on page {}; returning empty statement", page_number)
        return stmt  # no table => VLM-fallback territory

    # Classify each table's columns once; carry (ParsedTable, roles) through.
    parsed = [(pt, _column_roles(pt.df)) for pt in tables]
    selected = [pr for pr in parsed if _has_year_columns(pr[1])]
    if not selected:                                  # no year headers -> densest, positional
        selected = [max(parsed, key=lambda pr: _money_cells(pr[0].df))]
    densest = max(selected, key=lambda pr: _money_cells(pr[0].df))
    _apply_context(stmt, pdf_path, page_number, densest[0].df)
    for pt, roles in selected:
        stmt.line_items.extend(_table_to_items(pt, page_number, roles))
    logger.info("Parsed {} line item(s) from {}/{} table(s) on page {}",
                len(stmt.line_items), len(selected), len(tables), page_number)
    return stmt


import re
from pathlib import Path

from loguru import logger
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

from ..schemas import LineItem, Statement, Provenance
from .units import detect_units, detect_currency, detect_sign_convention
from .text import extract_pages

# Strict money cell: thousands-grouped, 3+ digit integer, or decimal; parens = negative.
_MONEY = re.compile(r"^\(?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d{3,}|\d+\.\d+)\)?$")
# Note reference: a small integer, optionally with a letter sub-part, as a
# comma-list, e.g. "4", "26", "3(a)", "3a", "5, 6", "3(a), 3(b)".
_NOTE = re.compile(r"^\d{1,2}(?:\([a-z]\)|[a-z])?(?:\s*,\s*\d{1,2}(?:\([a-z]\)|[a-z])?)*$", re.I)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SKIP = ("year ended", "for the year", "annual report")
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

def _parse_note_refs(note_raw: str | None) -> list[int]:
    """Pull the note numbers out of a raw note cell, e.g. '3(a), 4' -> [3, 4]."""
    if not note_raw:
        return []
    return [int(n) for n in re.findall(r"\d{1,2}", note_raw)]

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
        
# Docling Table Structure Recognizer
def _build_converter() -> DocumentConverter:
    logger.debug("Building docling PDF converter with table structure enabled")
    opts = PdfPipelineOptions(do_table_structure=True)
    opts.table_structure_options.mode = TableFormerMode.ACCURATE # ACCURATE | FAST
    opts.do_ocr = False  # text-based reports; OCR off for speed
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )

# Docling DF uses NaN for empty cells
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
def _numeric_density(table) -> int:
    try:
        df = table.export_to_dataframe()
    except Exception:
        return 0
    flat = df.astype(str).to_numpy().ravel()
    return sum(1 for c in flat if _MONEY.match(str(c).strip()))

# detect years
def _detect_years(df) -> tuple[int | None, int | None]:
    blob = " ".join(str(x) for x in df.columns) + " " + \
            " ".join(df.astype(str).to_numpy().ravel().tolist())
    years = sorted({int(y) for y in _YEAR.findall(blob)}, reverse=True)
    return (years[0] if years else None, years[1] if len(years) > 1 else None)

def _row_to_item(cells: list[str]) -> LineItem | None:
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

    low = label.lower()
    return LineItem(
        label_raw=label,
        value_current=vals[0],
        value_prior=vals[1] if len(vals) > 1 else None,
        note_ref_raw=note_raw,
        note_refs=_parse_note_refs(note_raw),
        is_subtotal=any(m in low for m in _SUBTOTAL_MARKERS),
    )

def parse_income_statement(pdf: Path | str, page_number: int) -> Statement:
    pdf_path = Path(pdf)
    logger.info("Parsing income statement from {} page {}", pdf_path.name, page_number)
    result = _build_converter().convert(str(pdf), page_range=(page_number, page_number))
    doc = result.document

    stmt = Statement(source_pdf=pdf_path.name, statement_pages=[page_number])
    if not doc.tables:
        logger.warning("No tables found on page {}; returning empty statement", page_number)
        return stmt  # no table => VLM-fallback territory

    table = max(doc.tables, key=_numeric_density)    # densest table on the page
    logger.debug("Selected densest table from {} candidate(s)", len(doc.tables))
    df = table.export_to_dataframe()
    stmt.year_current, stmt.year_prior = _detect_years(df)

    page_text = next((p.text for p in extract_pages(pdf_path) if p.number == page_number), "")
    stmt.units = detect_units(page_text)
    stmt.currency = detect_currency(page_text)
    stmt.sign_convention = detect_sign_convention(page_text)
    logger.info(
        "Detected context for {} page {}: year_current={}, year_prior={}, units={}, currency={}, sign_convention={}",
        pdf_path.name,
        page_number,
        stmt.year_current,
        stmt.year_prior,
        stmt.units,
        stmt.currency,
        stmt.sign_convention,
    )
    prov_bbox = None
    if table.prov:
        b = table.prov[0].bbox
        prov_bbox = (b.l, b.t, b.r, b.b)             # four floats, per schema

    parsed_items = 0
    for _, row in df.iterrows():
        cells = row.tolist()
        item = _row_to_item(cells)
        if item:
            item.page = page_number
            item.provenance = Provenance(
                page=page_number,
                bbox=prov_bbox,
                raw_cell_text=" | ".join(c for c in _clean(cells) if c),
            )
            stmt.line_items.append(item)
            parsed_items += 1
    logger.info("Parsed {} line item(s) from {} page {}", parsed_items, pdf_path.name, page_number)
    return stmt


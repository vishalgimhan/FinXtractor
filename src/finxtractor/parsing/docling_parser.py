import re
from pathlib import Path

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

from ..schemas import LineItem, Statement, Provenance

# Strict money cell: thousands-grouped, 3+ digit integer, or decimal; parens = negative.
_MONEY = re.compile(r"^\(?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d{3,}|\d+\.\d+)\)?$")
# Note reference: a small integer or comma-list, e.g. "4" or "5, 6".
_NOTE = re.compile(r"^\d{1,2}(?:\s*,\s*\d{1,2})*$")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_SKIP = ("year ended", "for the year", "annual report")

# Docling Table Structure Recognizer
def _build_converter() -> DocumentConverter:
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

    return LineItem(
        label_raw=label,
        value_current=vals[0],
        value_prior=vals[1] if len(vals) > 1 else None,
        note_ref_raw=note_raw,
        is_subtotal="total" in label.lower(),
    )

def parse_income_statement(pdf: Path | str, page_number: int) -> Statement:
    result = _build_converter().convert(str(pdf), page_range=(page_number, page_number))
    doc = result.document

    stmt = Statement(source_pdf=Path(pdf).name, statement_pages=[page_number])
    if not doc.tables:
        return stmt  # no table => VLM-fallback territory

    table = max(doc.tables, key=_numeric_density)    # densest table on the page
    df = table.export_to_dataframe()
    stmt.year_current, stmt.year_prior = _detect_years(df)

    prov_bbox = None
    if table.prov:
        b = table.prov[0].bbox
        prov_bbox = (b.l, b.t, b.r, b.b)             # four floats, per schema

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
    return stmt
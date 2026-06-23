import re
from .text import Page
from ..schemas import LineItem, Statement

# thousands groups, 3+ digit integers, decimals, parenthesized negatives
_MONEY = re.compile(
    r"\(?\$?\s?(?:\d{1,3}(?:,\d{3})+|\d{3,}|\d+\.\d+)(?:\.\d+)?\)?"
)

# A note reference at the end of the label region: "4" or "4, 5".
_NOTE_TAIL = re.compile(r"(\d{1,2}(?:\s*,\s*\d{1,2})*)\s*$")

_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")

# Obvious non-data lines we never want as rows.
_SKIP = ("year ended", "for the year", "annual report", "consolidated entity")

def _to_float(token: str) -> float:
    neg = "(" in token
    digits = re.sub(r"[(),$\s]", "", token)
    value = float(digits)
    return -value if neg else value

def _detect_years(text: str) -> tuple[int | None, int | None]:
    years = sorted({int(y) for y in _YEAR.findall(text)}, reverse=True)
    current = years[0] if years else None
    prior = years[1] if len(years) > 1 else None
    return current, prior

def _parse_line(line: str) -> LineItem | None:
    low = line.lower()
    if any(s in low for s in _SKIP):
        return None

    money = list(_MONEY.finditer(line))
    if not money:
        return None  # no figures => heading/blank line

    value_tokens = money[-2:]  # rightmost two = the year columns
    label_region = line[: value_tokens[0].start()].strip()

    note_raw = None
    m = _NOTE_TAIL.search(label_region)
    if m:
        note_raw = m.group(1)
        label_region = label_region[: m.start()].strip()

    if not label_region:
        return None  # all numbers, no label (e.g. the year header row)

    vals = [_to_float(t.group()) for t in value_tokens]
    return LineItem(
        label_raw=label_region,
        value_current=vals[0],
        value_prior=vals[1] if len(vals) > 1 else None,
        note_ref_raw=note_raw,
        is_subtotal="total" in label_region.lower(),
    )

def parse_income_statement(
       pages: list[Page], page_number: int, source_pdf: str
   ) -> Statement:
       page = next(p for p in pages if p.number == page_number)
       current, prior = _detect_years(page.text)
       stmt = Statement(
           source_pdf=source_pdf,
           statement_pages=[page_number],
           year_current=current,
           year_prior=prior,
       )
       for raw in page.text.splitlines():
           item = _parse_line(raw)
           if item:
               item.page = page_number
               stmt.line_items.append(item)
       return stmt
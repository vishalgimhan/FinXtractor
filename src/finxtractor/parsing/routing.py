import re
from .text import Page

INCOME_MARKERS = [
    "statement of profit",
    "consolidated statement of financial income",
    "statement of comprehensive income",
    "statement of financial performance",
]

NOTES_MARKERS = [
    "notes to the financial statements",
    "notes to and forming part of",
]

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_NUMBER = re.compile(r"\$|\d[\d,]{2,}")

def _matches(text: str, markers: list[str]) -> bool:
    low = text.lower()
    return any(m in low for m in markers)

def find_income_pages(pages: list[Page]) -> list[int]:
    return [p.number for p in pages if _matches(p.text, INCOME_MARKERS)]

def find_notes_pages(pages: list[Page]) -> list[int]:
    return [p.number for p in pages if _matches(p.text, NOTES_MARKERS)]

def rank_income_pages(pages: list[Page]) -> list[int]:
    """Income hits, best-first: prefer pages that also look like a real table
    (has a year and many numeric tokens), which filters out TOC/auditor mentions."""
    scored = []
    for p in pages:
        if not _matches(p.text, INCOME_MARKERS):
            continue
        has_year = bool(_YEAR.search(p.text))
        num_count = len(_NUMBER.findall(p.text))
        score = (1 if has_year else 0, num_count)
        scored.append((score, p.number))
    scored.sort(reverse=True)
    return [num for _, num in scored]
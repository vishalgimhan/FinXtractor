"""Generic, statement-kind-agnostic extraction.

Which statement gets extracted is decided only by the `page` passed in (resolved
via routing.resolve_page with the relevant markers) — there is nothing income-
or balance-specific here. A new statement type needs only new markers and any
new canonical accounts, not new extraction code.
"""
from pathlib import Path

from ..config import get_param
from ..schemas import Statement
from ..schemas.canonical import CanonicalStatement
from .docling_parser import parse_statement, table_confidence
from ..services.vlm import extract_with_vlm
from .notes import resolve_line_item_notes
from ..normalize.normalize import normalize


def extract_statement(pdf: Path | str, page: int) -> Statement:
    """Raw extraction of whatever statement is on `page`: parse the page's
    table(s), fall back to the VLM on low TableFormer confidence, then resolve
    note references. Returns the raw Statement (line items + provenance)."""
    stmt = parse_statement(pdf, page)
    if table_confidence(stmt) < get_param("vlm", "confidence_floor", default=0.0):
        stmt = extract_with_vlm(pdf, page)
    resolve_line_item_notes(stmt)
    return stmt


def extract_canonical(pdf: Path | str, page: int, *, use_llm: bool = False) -> CanonicalStatement:
    """Canonical extraction: raw extract -> normalize to the canonical chart."""
    return normalize(extract_statement(pdf, page), use_llm=use_llm)

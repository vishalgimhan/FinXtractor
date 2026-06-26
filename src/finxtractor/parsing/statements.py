"""Generic, statement-kind-agnostic extraction.

Which statement gets extracted is decided only by the `page` passed in (resolved
via routing.resolve_page with the relevant markers) — there is nothing income-
or balance-specific here. A new statement type needs only new markers and any
new canonical accounts, not new extraction code.
"""
from pathlib import Path

from loguru import logger

from ..config import get_param
from ..schemas import Statement
from ..schemas.canonical import CanonicalStatement
from .docling_parser import parse_statement, table_confidence
from ..services.vlm import extract_with_vlm
from .notes import resolve_line_item_notes
from ..normalize.normalize import normalize


def extract_statement(pdf: Path | str, page: int, *, text_layer: str = "ok") -> Statement:
    """Raw extraction of whatever statement is on `page`, via an escalating
    ladder: TableFormer (text) -> TableFormer+OCR -> VLM. A tier is accepted when
    it yields line items at or above the confidence floor; otherwise the next
    tier is tried. For a scanned page (text_layer='none') the text-only tier is
    skipped (it has nothing to read). The best result is kept if all fall short."""
    floor = get_param("vlm", "confidence_floor", default=0.0)

    tiers = []
    if text_layer != "none":
        tiers.append(("tableformer", lambda: parse_statement(pdf, page)))
    tiers.append(("ocr", lambda: parse_statement(pdf, page, ocr=True)))
    tiers.append(("vlm", lambda: extract_with_vlm(pdf, page)))

    best: Statement | None = None
    best_conf = -1.0
    for name, run in tiers:
        try:
            stmt = run()
        except Exception as e:
            logger.warning("Extraction tier '{}' failed on page {}: {}", name, page, type(e).__name__)
            continue
        conf = table_confidence(stmt)
        logger.info("Extraction tier '{}' on page {}: {} item(s), confidence {:.2f}",
                    name, page, len(stmt.line_items), conf)
        if conf > best_conf:
            best, best_conf = stmt, conf
        if stmt.line_items and conf >= floor:
            break

    if best is None:                       # every tier errored
        best = Statement(source_pdf=Path(pdf).name, statement_pages=[page])
    resolve_line_item_notes(best)
    return best


def extract_canonical(pdf: Path | str, page: int, *, use_llm: bool = False,
                      text_layer: str = "ok") -> CanonicalStatement:
    """Canonical extraction: raw extract (ladder) -> normalize to the canonical chart."""
    return normalize(extract_statement(pdf, page, text_layer=text_layer), use_llm=use_llm)

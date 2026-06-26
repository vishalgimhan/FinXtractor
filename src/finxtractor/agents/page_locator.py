"""Locate statement pages on scanned / low-text PDFs, lazily.

Used as the deepest resolution tier when the TOC + text heuristics can't find a
page. Two stages, both early-stopping and budget-capped so the expensive models
never sweep the whole document:

  1. OCR scan  — OCR pages one at a time; lock a page for a kind only on a
                 *strong* match (marker + a year + several money figures), so a
                 mere contents-page mention doesn't win.
  2. VLM scan  — for any kind still missing, render pages and ask the vision
                 model to classify each, stopping as soon as it's found.
"""
from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger

from ..config import get_param, get_pattern
from ..parsing.text import Page
from ..parsing.outline import _matches
from ..services.ocr import ocr_page_text

_YEAR = get_pattern("year")
_NUMBER = get_pattern("number")


def _strong_match(text: str, markers: list[str], min_numeric: int) -> bool:
    """A real statement page: matches a marker AND looks like a table (a year +
    several money figures) — not just a title mentioned on a contents page."""
    if not _matches(text, markers):
        return False
    return bool(_YEAR.search(text)) and len(_NUMBER.findall(text)) >= min_numeric


def locate_scanned(pdf: Path | str, n_pages: int, marker_map: dict[str, list[str]],
                   *, text_layer: str = "ok", budget: int | None = None
                   ) -> dict[str, tuple[int, str]]:
    """Return {kind: (page, source)} for the kinds in `marker_map` that could be
    located by OCR scan then VLM classify. Early-stops once all are found."""
    budget = budget or get_param("triage", "max_scan_pages", default=60)
    min_numeric = get_param("triage", "min_statement_numeric", default=5)
    # Locating only needs legible headings to match markers, not clean figures, so
    # OCR the scan at a low DPI — it's ~3x faster than extraction DPI (150).
    scan_dpi = get_param("triage", "scan_dpi", default=100)
    limit = min(n_pages, budget)

    found: dict[str, tuple[int, str]] = {}
    remaining = dict(marker_map)

    # Stage 1: OCR scan, page by page, locking only on a strong match.
    for i in range(1, limit + 1):
        if not remaining:
            break
        text = ocr_page_text(pdf, i, dpi=scan_dpi)
        if not text.strip():
            continue
        for kind in list(remaining):
            if _strong_match(text, remaining[kind], min_numeric):
                found[kind] = (i, "ocr_scan")
                del remaining[kind]
                logger.info("OCR scan located {} on page {}", kind, i)

    # Stage 2: VLM classify whatever the OCR scan still missed.
    if remaining:
        found.update(_locate_vlm(pdf, limit, remaining))
    return found


def _locate_vlm(pdf: Path | str, limit: int,
                remaining: dict[str, list[str]]) -> dict[str, tuple[int, str]]:
    try:
        from pydantic import BaseModel
        from langchain_core.messages import HumanMessage
        from ..services.vlm import get_vlm_model
        from ..services.pdf_reader import get_pdf_reader
        from .prompts import page_classification_prompt
    except Exception as e:                       # langchain/pydantic missing
        logger.warning("VLM classifier deps unavailable: {}", type(e).__name__)
        return {}

    kinds = list(remaining)

    class _PageClass(BaseModel):
        kind: str | None                         # one of `kinds`, or None

    try:
        model = get_vlm_model().with_structured_output(_PageClass)
    except Exception as e:                        # no provider / API key
        logger.warning("VLM classifier unavailable: {}", type(e).__name__)
        return {}

    reader = get_pdf_reader()
    prompt = page_classification_prompt(kinds)
    found: dict[str, tuple[int, str]] = {}
    for i in range(1, limit + 1):
        if not remaining:
            break
        b64 = base64.b64encode(reader.render_page(pdf, i)).decode()
        message = HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ])
        try:
            result = model.invoke([message])
        except Exception as e:
            logger.warning("VLM classify failed on page {}: {}", i, type(e).__name__)
            continue
        kind = (result.kind or "").lower()
        if kind in remaining:
            found[kind] = (i, "vlm_classify")
            del remaining[kind]
            logger.info("VLM classifier located {} on page {}", kind, i)
    return found

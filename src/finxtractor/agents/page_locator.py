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
from functools import lru_cache
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
                   *, text_layer: str = "ok", budget: int | None = None,
                   use_vlm: bool = True) -> dict[str, tuple[int, str]]:
    """Return {kind: (page, source)} for the kinds in `marker_map` that could be
    located by OCR scan then (if `use_vlm`) VLM classify. Early-stops once all
    are found. Pass `use_vlm=False` for an OCR-only locate — the resolver agent
    drives the VLM tier separately via its vision sub-agent."""
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

    # Stage 2: VLM classify whatever the OCR scan still missed (unless disabled).
    if remaining and use_vlm:
        found.update(_locate_vlm(pdf, limit, remaining))
    return found


@lru_cache(maxsize=4)
def _vlm_classifier(kinds: tuple[str, ...]):
    """Vision model bound to a page-class schema for `kinds`, cached per kind set
    so the per-page classifier is built once, not per call."""
    from pydantic import BaseModel
    from ..services.vlm import get_vlm_model

    class _PageClass(BaseModel):
        kind: str | None                         # one of `kinds`, or None

    return get_vlm_model().with_structured_output(_PageClass)


def classify_page_vlm(pdf: Path | str, page: int, kinds: list[str]) -> str | None:
    """Render one page and ask the vision model which of `kinds` it primarily is,
    returning that kind (lowercased) or None. Best-effort: returns None if the
    VLM tier / deps are unavailable or the call fails. Shared by the OCR/VLM
    fallback sweep and the resolver's vision sub-agent."""
    try:
        from langchain_core.messages import HumanMessage
        from ..services.pdf_reader import get_pdf_reader
        from .prompts import page_classification_prompt
        model = _vlm_classifier(tuple(kinds))
    except Exception as e:                        # deps missing / no provider
        logger.warning("VLM classifier unavailable: {}", type(e).__name__)
        return None
    b64 = base64.b64encode(get_pdf_reader().render_page(pdf, page)).decode()
    message = HumanMessage(content=[
        {"type": "text", "text": page_classification_prompt(list(kinds))},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ])
    try:
        result = model.invoke([message])
    except Exception as e:
        logger.warning("VLM classify failed on page {}: {}", page, type(e).__name__)
        return None
    kind = (result.kind or "").lower()
    return kind if kind in kinds else None


def _locate_vlm(pdf: Path | str, limit: int,
                remaining: dict[str, list[str]]) -> dict[str, tuple[int, str]]:
    """Deterministic VLM sweep: classify pages 1..limit, locking each kind on the
    first page that classifies as it. Used by the non-agentic fallback path."""
    kinds = list(remaining)
    found: dict[str, tuple[int, str]] = {}
    for i in range(1, limit + 1):
        if not remaining:
            break
        kind = classify_page_vlm(pdf, i, kinds)
        if kind in remaining:
            found[kind] = (i, "vlm_classify")
            del remaining[kind]
            logger.info("VLM classifier located {} on page {}", kind, i)
    return found

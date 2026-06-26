"""Backend-agnostic contract for the vision-LLM fallback extractor.

A VLM extractor turns one rasterized PDF page into a `Statement` — the same
shape the deterministic TableFormer path produces — so callers can swap it in
when table confidence is low without knowing which vision model is behind it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ...schemas import Statement


@runtime_checkable
class VlmExtractor(Protocol):
    """Any vision-LLM extraction backend implements this."""

    def extract(self, pdf: Path | str, page_number: int) -> Statement:
        ...

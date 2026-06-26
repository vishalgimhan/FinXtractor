"""Backend-agnostic contract for reading PDFs.

A PDF reader is the substrate layer: page text, the embedded outline, page
count, and page rasterization. Swapping the engine (PyMuPDF, pdfplumber,
pypdfium2, ...) means writing one new implementation, not touching the routing /
text-extraction logic that consumes it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class PdfReader(Protocol):
    """Any PDF-reading backend implements this."""

    def page_count(self, pdf: Path | str) -> int:
        ...

    def page_texts(self, pdf: Path | str) -> list[str]:
        """Plain text per page, 0-based (one string per physical page)."""
        ...

    def outline(self, pdf: Path | str) -> list[tuple[int, str, int]]:
        """Embedded outline/bookmarks as (level, title, 1-based page). Empty if none."""
        ...

    def render_page(self, pdf: Path | str, page_number: int, dpi: int | None = None) -> bytes:
        """Rasterize a 1-based page to PNG bytes (dpi falls back to the backend default)."""
        ...

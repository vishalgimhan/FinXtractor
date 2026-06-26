"""PyMuPDF (fitz) PDF-reading backend."""
from __future__ import annotations

from pathlib import Path


class PyMuPdfReader:
    """Read PDFs with PyMuPDF. `render_dpi` is the default rasterization DPI,
    from the `pymupdf` provider block in config/models.yaml -> pdf_reader."""

    def __init__(self, render_dpi: int = 150):
        self.render_dpi = render_dpi

    @staticmethod
    def _open(pdf: Path | str):
        # Lazy import so the package imports without PyMuPDF installed; only this
        # backend needs it (mirrors the lazy imports in the other backends).
        import fitz
        return fitz.open(pdf)

    def page_count(self, pdf: Path | str) -> int:
        doc = self._open(pdf)
        try:
            return doc.page_count
        finally:
            doc.close()

    def page_texts(self, pdf: Path | str) -> list[str]:
        doc = self._open(pdf)
        try:
            return [doc.load_page(i).get_text() for i in range(doc.page_count)]
        finally:
            doc.close()

    def outline(self, pdf: Path | str) -> list[tuple[int, str, int]]:
        doc = self._open(pdf)
        try:
            return [tuple(entry) for entry in doc.get_toc()]  # [level, title, 1-based page]
        finally:
            doc.close()

    def render_page(self, pdf: Path | str, page_number: int, dpi: int | None = None) -> bytes:
        doc = self._open(pdf)
        try:
            pix = doc.load_page(page_number - 1).get_pixmap(dpi=dpi or self.render_dpi)
            return pix.tobytes("png")
        finally:
            doc.close()

"""Swappable PDF-reading backends.

`get_pdf_reader()` is the single entry point — it reads the active backend from
config/models.yaml (pdf_reader.active) and lazy-imports it, the same way
get_table_extractor() / get_chat_model() select their backends.
"""
from functools import lru_cache

from ...config import load_active_pdf_reader
from .base import PdfReader

__all__ = ["PdfReader", "get_pdf_reader"]


@lru_cache(maxsize=1)
def get_pdf_reader() -> PdfReader:
    active, cfg = load_active_pdf_reader()
    if active == "pymupdf":
        from .pymupdf import PyMuPdfReader
        return PyMuPdfReader(**cfg)
    raise ValueError(f"Unknown PDF reader backend: {active}")

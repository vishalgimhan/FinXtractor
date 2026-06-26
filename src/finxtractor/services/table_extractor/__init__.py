"""Swappable table-extraction backends.

`get_table_extractor()` is the single entry point — it reads the active backend
from config/models.yaml (table_extraction.active) and lazy-imports it, the same
way llm/providers/ selects an LLM provider.
"""
from functools import lru_cache

from ...config import load_active_table_extractor
from .base import ParsedTable, TableExtractor

__all__ = ["ParsedTable", "TableExtractor", "get_table_extractor"]


@lru_cache(maxsize=4)
def get_table_extractor(do_ocr: bool | None = None) -> TableExtractor:
    """Active table backend. Pass do_ocr to override the configured OCR setting
    (the OCR tier of the extraction ladder uses do_ocr=True); None keeps the
    config value. Cached per do_ocr value so each variant is built once."""
    active, cfg = load_active_table_extractor()
    if do_ocr is not None:
        cfg = {**cfg, "do_ocr": do_ocr}
    if active == "docling":
        from .docling import DoclingTableExtractor
        return DoclingTableExtractor(**cfg)
    raise ValueError(f"Unknown table-extraction backend: {active}")

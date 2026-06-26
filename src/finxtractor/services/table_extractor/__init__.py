"""Swappable table-extraction backends.

`get_table_extractor()` is the single entry point — it reads the active backend
from config/models.yaml (table_extraction.active) and lazy-imports it, the same
way llm/providers/ selects an LLM provider.
"""
from functools import lru_cache

from ...config import load_active_table_extractor
from .base import ParsedTable, TableExtractor

__all__ = ["ParsedTable", "TableExtractor", "get_table_extractor"]


@lru_cache(maxsize=1)
def get_table_extractor() -> TableExtractor:
    active, cfg = load_active_table_extractor()
    if active == "docling":
        from .docling import DoclingTableExtractor
        return DoclingTableExtractor(**cfg)
    raise ValueError(f"Unknown table-extraction backend: {active}")

"""Backend-agnostic contract for table extraction.

A table extractor turns one PDF page into a list of `ParsedTable`s — each a
pandas DataFrame plus an optional bounding box. Everything downstream in
docling_parser.py works off this neutral shape, so swapping the engine (Docling,
another OCR/table backend, a cloud API) means writing one new implementation,
not touching the parsing logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd


@dataclass
class ParsedTable:
    """One detected table in a neutral representation."""
    df: pd.DataFrame
    bbox: tuple[float, float, float, float] | None = None  # (l, t, r, b)


@runtime_checkable
class TableExtractor(Protocol):
    """Any table-extraction backend implements this."""

    def extract_tables(self, pdf: Path | str, page_number: int) -> list[ParsedTable]:
        ...

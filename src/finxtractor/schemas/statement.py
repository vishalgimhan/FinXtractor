from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from .note import NoteRef

class Units(str, Enum):
    ACTUAL = "actual"
    THOUSANDS = "thousands"
    MILLIONS = "millions"

class Provenance(BaseModel):
    page: int                                                    # 1-based source page
    bbox: Optional[tuple[float, float, float, float]] = None     # (l, t, r, b), PDF points
    raw_cell_text: Optional[str] = None                          # raw row text Docling read


class LineItem(BaseModel):
    label_raw: str                                       # exactly as printed
    label_canonical: Optional[str] = None                # filled by normalizer (later)
    value_current: Optional[float] = None                # current-year figure, signed
    value_prior: Optional[float] = None                  # comparative-year figure, signed
    note_ref_raw: Optional[str] = None                   # raw cell, e.g. "4, 5" or "3(a)"
    note_refs: list[NoteRef] = Field(default_factory=list)   # parsed tokens, e.g. ["3(a)"]
    page: Optional[int] = None                           # 1-based source page
    is_subtotal: bool = False                            # marks total/subtotal rows
    provenance: Optional[Provenance] = None                 # filled by parser

class Statement(BaseModel):
    source_pdf: str
    statement_pages: list[int] = Field(default_factory=list)
    year_current: Optional[int] = None
    year_prior: Optional[int] = None
    currency: str = "AUD"
    units: Units = Units.ACTUAL
    sign_convention: str = "parentheses_negative"
    line_items: list[LineItem] = Field(default_factory=list)
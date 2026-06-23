from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class Units(str, Enum):
    ACTUAL = "actual"
    THOUSANDS = "thousands"
    MILLIONS = "millions"

class LineItem(BaseModel):
    label_raw: str                                       # exactly as printed
    label_canonical: Optional[str] = None                # filled by normalizer (later)
    value_current: Optional[float] = None                # current-year figure, signed
    value_prior: Optional[float] = None                  # comparative-year figure, signed
    note_ref_raw: Optional[str] = None                   # raw cell, e.g. "4, 5"
    note_refs: list[int] = Field(default_factory=list)   # parsed; filled by note-linker
    page: Optional[int] = None                           # 1-based source page
    is_subtotal: bool = False                            # marks total/subtotal rows

class Statement(BaseModel):
    source_pdf: str
    statement_pages: list[int] = Field(default_factory=list)
    year_current: Optional[int] = None
    year_prior: Optional[int] = None
    currency: str = "AUD"
    units: Units = Units.ACTUAL
    line_items: list[LineItem] = Field(default_factory=list)
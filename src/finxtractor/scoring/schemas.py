from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class MetricInput(BaseModel):
    """One input to a ratio/score, with where it came from."""
    account: str
    value: Decimal
    page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None

class Ratio(BaseModel):
    name: str
    value: Optional[Decimal] = None            # None when undefined (e.g. zero denominator)
    formula: str                               # human-readable, e.g. "net_profit / revenue"
    inputs: list[MetricInput] = Field(default_factory=list)
    note: str = ""                             # e.g. "undefined: interest_expense is zero"


class Zone(str, Enum):
    SAFE = "safe"
    GREY = "grey"
    DISTRESS = "distress"


class AltmanResult(BaseModel):
    x1: Optional[Decimal] = None               # working capital / total assets
    x2: Optional[Decimal] = None               # retained earnings / total assets
    x3: Optional[Decimal] = None               # EBIT / total assets
    x4: Optional[Decimal] = None               # book equity / total liabilities
    z_double_prime: Optional[Decimal] = None
    zone: Optional[Zone] = None
    inputs: list[MetricInput] = Field(default_factory=list)

class CompositeScore(BaseModel):
    score_0_100: Optional[Decimal] = None
    grade: Optional[str] = None                # "A".."F" by threshold table
    components: dict[str, Decimal] = Field(default_factory=dict)  # per-metric sub-scores
    notes: list[str] = Field(default_factory=list)


class CreditReport(BaseModel):
    source_pdf: str
    year: Optional[int] = None
    ratios: list[Ratio] = Field(default_factory=list)
    altman: Optional[AltmanResult] = None
    composite: Optional[CompositeScore] = None
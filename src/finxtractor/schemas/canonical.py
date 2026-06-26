from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

from .note import NoteRef
from .statement import Units, Provenance


class CanonicalAccount(str, Enum):
    # --- Income statement ---
    REVENUE = "revenue"
    COST_OF_SALES = "cost_of_sales"
    GROSS_PROFIT = "gross_profit"
    OPERATING_EXPENSES = "operating_expenses"
    EBIT = "ebit"                          # operating profit; Altman X3
    INTEREST_EXPENSE = "interest_expense"
    PROFIT_BEFORE_TAX = "profit_before_tax"
    INCOME_TAX_EXPENSE = "income_tax_expense"
    NET_PROFIT = "net_profit"
    # --- Balance sheet (the targeted pull) ---
    CURRENT_ASSETS = "current_assets"      # current ratio; Altman X1
    TOTAL_ASSETS = "total_assets"          # Altman X1, X2, X3 denominator
    CURRENT_LIABILITIES = "current_liabilities"  # current ratio; Altman X1
    TOTAL_LIABILITIES = "total_liabilities"      # D/E; Altman X4 denominator
    TOTAL_EQUITY = "total_equity"          # D/E; Altman X4 (book value)
    RETAINED_EARNINGS = "retained_earnings"      # Altman X2

class CanonicalLine(BaseModel):
    account: CanonicalAccount
    value_current: Optional[Decimal] = None       # normalized, absolute units
    value_prior: Optional[Decimal] = None
    source_labels: list[str] = Field(default_factory=list)  # raw labels that mapped here
    note_refs: list[NoteRef] = Field(default_factory=list)  # notes cited by the source row(s)
    mapped_by: str = "alias"                       # "alias" | "fuzzy" | "llm"
    provenance: Optional[Provenance] = None          # from the source row that mapped here

class CanonicalStatement(BaseModel):
    source_pdf: str
    statement_pages: list[int] = Field(default_factory=list)
    year_current: Optional[int] = None
    year_prior: Optional[int] = None
    currency: str = "AUD"
    units: Units = Units.ACTUAL              # source rounding unit; canonical values are absolute
    sign_convention: str = "parentheses_negative"
    lines: dict[str, CanonicalLine] = Field(default_factory=dict)  # keyed by account value

    def get(self, account: CanonicalAccount) -> Optional[CanonicalLine]:
        return self.lines.get(account.value)
from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"

class CheckResult(BaseModel):
    name: str                              # e.g. "income_identity"
    status: CheckStatus
    expected: Optional[Decimal] = None     # what the identity requires
    actual: Optional[Decimal] = None       # what was extracted
    difference: Optional[Decimal] = None   # actual - expected
    tolerance: Optional[Decimal] = None    # allowed slack (rounding)
    accounts: list[str] = Field(default_factory=list)   # accounts this check touched
    message: str = ""                      # human-readable; also fed to the LLM on retry

class ValueConfidence(BaseModel):
    account: str
    year: str                              # "current" | "prior" or the fiscal year
    score: float                           # 0.0 - 1.0
    extraction_source: str                 # "tableformer" | "vlm" | "llm_mapped"
    checks_passed: int = 0
    checks_failed: int = 0
    flagged_for_review: bool = False       # set by the HITL gate (M5)
    reasons: list[str] = Field(default_factory=list)   # why this score / why flagged

class ValidationReport(BaseModel):
    checks: list[CheckResult] = Field(default_factory=list)
    confidences: list[ValueConfidence] = Field(default_factory=list)
    retries: int = 0
    flagged_count: int = 0

    @property
    def passed(self) -> bool:
        return all(c.status != CheckStatus.FAIL for c in self.checks)
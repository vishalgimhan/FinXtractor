from __future__ import annotations
from typing import Optional, TypedDict
from ..schemas.canonical import CanonicalStatement
from ..validate.results import CheckResult, ValueConfidence, ValidationReport


class PipelineState(TypedDict, total=False):
    # --- inputs (set at invoke) ---
    pdf: str
    income_page: int
    bs_page: Optional[int]
    # --- produced as the run progresses ---
    statement: Optional[CanonicalStatement]
    checks: list[CheckResult]
    confidences: list[ValueConfidence]
    report: Optional[ValidationReport]
    # --- control-flow bookkeeping (the old while-loop variables) ---
    retries: int
    max_retries: int
    prev_failed_count: Optional[int]
    route: str            # last routing decision — recorded for observability
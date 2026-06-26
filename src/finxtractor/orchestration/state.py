from __future__ import annotations
from typing import Optional, TypedDict
from ..schemas.canonical import CanonicalStatement
from ..validate.results import CheckResult, ValueConfidence, ValidationReport
from ..agents.toc import StructuredToc


class PipelineState(TypedDict, total=False):
    # --- inputs (set at invoke) ---
    pdf: str
    income_page: Optional[int]      # optional override; else the resolver fills it
    bs_page: Optional[int]          # optional override; else the resolver fills it
    # --- produced as the run progresses ---
    income_page_source: str         # "override" | "agentic_toc" | "outline" | "printed_toc" | ...
    bs_page_source: str
    toc: Optional[StructuredToc]     # agentic structured contents page, reusable for note pages
    statement: Optional[CanonicalStatement]
    checks: list[CheckResult]
    confidences: list[ValueConfidence]
    report: Optional[ValidationReport]
    # --- control-flow bookkeeping (the old while-loop variables) ---
    retries: int
    max_retries: int
    prev_failed_count: Optional[int]
    route: str            # last routing decision — recorded for observability
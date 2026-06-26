from __future__ import annotations
from typing import Optional, TypedDict
from ..schemas.canonical import CanonicalStatement
from ..validate.results import CheckResult, ValueConfidence, ValidationReport
from ..parsing.outline import PageIndex
from ..scoring.schemas import CreditReport


class PipelineState(TypedDict, total=False):
    # --- inputs (set at invoke) ---
    pdf: str
    income_page: Optional[int]      # optional override; else the resolver fills it
    bs_page: Optional[int]          # optional override; else the resolver fills it
    # --- produced as the run progresses ---
    income_page_source: str         # "override" | "agentic_toc" | "outline" | "printed_toc" | ...
    bs_page_source: str
    text_layer: str                 # "ok" | "sparse" | "none" (scanned) -> drives OCR/VLM routing
    resolution_error: Optional[str] # set when no statement page could be located
    page_index: Optional[PageIndex]  # unified title->page index (agentic TOC + outline)
    statement: Optional[CanonicalStatement]
    checks: list[CheckResult]
    confidences: list[ValueConfidence]
    report: Optional[ValidationReport]
    credit_report: Optional[CreditReport]   # produced by the scoring node (clean route)
    # --- control-flow bookkeeping (the old while-loop variables) ---
    retries: int
    max_retries: int
    prev_failed_count: Optional[int]
    route: str            # last routing decision — recorded for observability
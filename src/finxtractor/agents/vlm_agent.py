"""Vision (VLM) agent — the shared vision capability for the pipeline.

Two entry points over one VLM backend, consulted by the `vlm` graph node on
behalf of whichever agent escalated to it:

  - `locate_with_vlm`  — find ONE statement page in a scan by classifying page
    ranges. Genuinely agentic: a text-LLM controller picks ranges via the
    `scan_pages` tool while the VLM does the seeing inside the tool, keeping
    controller turns coarse. (Resolver's vision need.)
  - `extract_with_vlm_agent` — read the statement table on a GIVEN page into a
    Statement. One-shot (a single page, a single structured vision call), so no
    controller loop is needed. (Extractor's vision need.)

Both are best-effort: if the LLM or VLM tier is unavailable they return a miss /
None and the caller simply moves on.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from .prompts import vlm_locator_system_prompt, vlm_locator_user_prompt
from .tools.vlm import VlmContext, build_vlm_tools
from ..config import get_param
from ..schemas import Statement
from ..services.pdf_reader import get_pdf_reader


class VlmLocateResult(BaseModel):
    """The vision agent's final answer for one kind."""
    found: bool = False
    page: int | None = Field(None, description="1-based page the statement is on, if found")


def locate_with_vlm(pdf: Path | str, kind: str, *, hint_page: int | None = None,
                    n_pages: int | None = None) -> tuple[int | None, str | None]:
    """Locate `kind` ('income'/'balance') via the vision agent. Returns
    (page, 'vlm_classify') or (None, None). Best-effort: any failure (no LLM/VLM
    provider, deps missing, API error) yields a miss rather than raising."""
    try:
        return _run(Path(pdf), kind, hint_page, n_pages)
    except Exception as e:
        logger.warning("VLM agent unavailable ({}); skipping vision tier",
                       type(e).__name__)
        return None, None


def _run(pdf: Path, kind: str, hint_page: int | None,
         n_pages: int | None) -> tuple[int | None, str | None]:
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage
    from ..services.llm import get_chat_model

    if n_pages is None:
        n_pages = get_pdf_reader().page_count(pdf)
    budget = get_param("triage", "max_scan_pages", default=60)
    ctx = VlmContext(pdf=pdf, n_pages=n_pages, budget=budget)

    agent = create_react_agent(
        get_chat_model(),
        build_vlm_tools(ctx),
        prompt=vlm_locator_system_prompt(),
        response_format=VlmLocateResult,
    )
    user = vlm_locator_user_prompt(kind, n_pages, hint_page)
    out = agent.invoke({"messages": [HumanMessage(user)]})
    res: VlmLocateResult = out["structured_response"]
    if res.found and res.page is not None and 1 <= res.page <= n_pages:
        return res.page, "vlm_classify"
    return None, None


def extract_with_vlm_agent(pdf: Path | str, page: int) -> Statement | None:
    """Read the statement table on `page` via the vision model, returning a raw
    Statement (the same shape the TableFormer path yields) or None if the VLM
    tier is unavailable / the call fails. One-shot: a single page, no loop."""
    try:
        from ..services.vlm import extract_with_vlm
        return extract_with_vlm(pdf, page)
    except Exception as e:
        logger.warning("VLM extraction unavailable ({}) on page {}",
                       type(e).__name__, page)
        return None

"""Agentic credit analyst (the scoring narrative).

An LLM agent that turns the deterministically-computed `CreditReport` into a
structured `CreditAssessment` — summary, drivers, concerns, outlook,
recommendation. It computes nothing: it inspects the ratios / Altman / composite
/ risk flags through read-only tools and grounds its concerns in provenance
(source page + raw label) via `trace_ratio`.

Purely additive and best-effort: if the LLM tier is unavailable it returns None
and the scoring node keeps the deterministic report without a narrative.
"""
from __future__ import annotations

from loguru import logger

from .prompts import analyst_system_prompt, analyst_user_prompt
from .tools.analyst import AnalystContext, build_analyst_tools
from ..scoring.schemas import CreditReport, CreditAssessment
from ..schemas.canonical import CanonicalStatement


def assess(report: CreditReport,
           statement: CanonicalStatement | None = None) -> CreditAssessment | None:
    """Write the analyst narrative for `report`, or None if the LLM tier is down
    (any failure degrades gracefully — the deterministic report still stands)."""
    try:
        return _run(report, statement)
    except Exception as e:
        logger.warning("Analyst agent unavailable ({}); skipping narrative",
                       type(e).__name__)
        return None


def _run(report: CreditReport,
         statement: CanonicalStatement | None) -> CreditAssessment:
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage
    from ..services.llm import get_chat_model

    ctx = AnalystContext(report=report, statement=statement)
    agent = create_react_agent(
        get_chat_model(),
        build_analyst_tools(ctx),
        prompt=analyst_system_prompt(),
        response_format=CreditAssessment,
    )
    comp = report.composite
    score = comp.score_0_100 if comp else None
    grade = comp.grade if comp else None
    user = analyst_user_prompt(report.source_pdf, report.year, score, grade)
    out = agent.invoke({"messages": [HumanMessage(user)]})
    return out["structured_response"]

from __future__ import annotations
import uuid
from pathlib import Path
from dataclasses import dataclass, field

from loguru import logger

from .graph import compiled_pipeline


@dataclass
class DocResult:
    pdf: str
    thread_id: str
    route: str                       # "scoring" | "hitl" | "error"
    retries: int = 0
    flagged: int = 0
    error: str | None = None
    report: object = None            # the ValidationReport, or None on error

@dataclass
class DocSpec:
    pdf: str
    income_page: int | None = None   # optional override; else the resolver locates it
    bs_page: int | None = None       # optional override; else the resolver locates it


def _run_one(graph, spec: DocSpec, max_retries: int) -> DocResult:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial = {"pdf": spec.pdf, "income_page": spec.income_page,
               "bs_page": spec.bs_page, "retries": 0, "max_retries": max_retries}
    try:
        logger.info("Starting orchestration for {} (thread_id={})", spec.pdf, thread_id)
        final = graph.invoke(initial, config)
        logger.info("Finished orchestration for {} with route={} and {} retry(ies)", spec.pdf, final.get("route", "unknown"), final.get("retries", 0))
        return DocResult(pdf=spec.pdf, thread_id=thread_id,
                         route=final.get("route", "unknown"),
                         retries=final.get("retries", 0),
                         flagged=final["report"].flagged_count,
                         report=final["report"])
    except Exception as e:
        logger.exception("Orchestration failed for {}", spec.pdf)
        return DocResult(pdf=spec.pdf, thread_id=thread_id, route="error", error=str(e))

def orchestrate(specs: list[DocSpec], max_retries: int = 2) -> list[DocResult]:
    """Run every document through the pipeline graph independently."""
    logger.info("Orchestrating {} document(s) with max_retries={}", len(specs), max_retries)
    graph = compiled_pipeline()                # one compiled graph, reused per doc
    results = [_run_one(graph, spec, max_retries) for spec in specs]
    logger.info("Completed orchestration for {} document(s)", len(results))
    return results
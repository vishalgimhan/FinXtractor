"""FastAPI service exposing the FinXtractor LangGraph pipeline.

The key endpoint streams one event per graph stage (resolver -> extractor ->
validator -> scoring, with vlm/retry/hitl branches) over Server-Sent Events, so
the dashboard can light up each stage live instead of waiting on a blocking run.

Run it with:  poetry run uvicorn api.main:app --reload   (or `make api`)
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterator, AsyncIterator

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from loguru import logger

from finxtractor.config import get_param
from finxtractor.orchestration.graph import compiled_pipeline

from .events import NODE_LABELS, serialize_final, sse, stage_payload

_DEFAULT_RETRIES = get_param("validation", "max_retries", default=2)

app = FastAPI(title="FinXtractor Pipeline API", version="0.1.0")

# Streamlit runs on a different origin; allow the browser/client to reach us.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness probe + the ordered list of pipeline stages the API can emit."""
    return {"status": "ok", "stages": [{"node": n, "label": l}
                                        for n, l in NODE_LABELS.items()]}


async def _run_stream(pdf: str, max_retries: int) -> AsyncIterator[str]:
    """Drive the compiled graph and yield SSE frames:
    a `start` frame, `step` frames (for tools/LLM calls), `stage` frames (for node updates),
    then a `done` (or `error`)."""
    graph = compiled_pipeline()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    initial = {"pdf": pdf, "income_page": None, "bs_page": None,
               "retries": 0, "max_retries": max_retries}

    logger.info("Streaming pipeline for {} (thread_id={})", pdf, thread_id)
    yield sse("start", {
        "pdf": pdf,
        "thread_id": thread_id,
        "stages": [{"node": n, "label": l} for n, l in NODE_LABELS.items()],
    })
    try:
        async for event in graph.astream_events(initial, config, version="v2"):
            kind = event.get("event")
            name = event.get("name")

            if kind == "on_tool_start":
                yield sse("step", {
                    "type": "tool_start",
                    "name": name,
                    "inputs": event["data"].get("input")
                })
            elif kind == "on_tool_end":
                yield sse("step", {
                    "type": "tool_end",
                    "name": name,
                    "output": event["data"].get("output")
                })
            elif kind == "on_chat_model_start":
                yield sse("step", {
                    "type": "llm_start",
                    "name": name
                })
            elif kind == "on_chain_end" and name in NODE_LABELS:
                output = event["data"].get("output")
                if output:
                    yield sse("stage", stage_payload(name, output))

        final = graph.get_state(config).values
        logger.info("Pipeline stream finished for {} (route={})",
                    pdf, final.get("route"))
        yield sse("done", serialize_final(final))
    except Exception as e:  # surface the failure to the client instead of hanging
        logger.exception("Pipeline stream failed for {}", pdf)
        yield sse("error", {"message": str(e)})


@app.get("/pipeline/stream")
async def pipeline_stream(
    pdf: str = Query(..., description="Path to the PDF, e.g. data/reports/CITIGROUP.pdf"),
    max_retries: int = Query(default=_DEFAULT_RETRIES, ge=0, le=5),
) -> StreamingResponse:
    """Run the pipeline for one report, streaming stage events as SSE."""
    if not Path(pdf).exists():
        return JSONResponse(status_code=404, content={"error": f"PDF not found: {pdf}"})
    return StreamingResponse(
        _run_stream(pdf, max_retries),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

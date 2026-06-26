"""Vision-LLM extractor: rasterize a page, ask a vision model to read the
statement table, map the structured reply onto the canonical `Statement`.

Provider-agnostic — it works off any langchain chat model that accepts image
content (ChatOllama / ChatOpenAI), so the same class serves every VLM provider.
"""
from __future__ import annotations

import base64
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, Field

from ...schemas import LineItem, Provenance, Statement, Units
from ..pdf_reader import get_pdf_reader


# Lean schema the model fills via structured output, then mapped onto Statement.
class _VlmLine(BaseModel):
    label: str
    value_current: float | None = None
    value_prior: float | None = None
    note_ref: str | None = None
    is_subtotal: bool = False


class _VlmStatement(BaseModel):
    year_current: int | None = None
    year_prior: int | None = None
    currency: str | None = None
    units: str | None = None
    line_items: list[_VlmLine] = Field(default_factory=list)


_UNITS = {"actual": Units.ACTUAL, "thousands": Units.THOUSANDS, "millions": Units.MILLIONS}


class VlmStatementExtractor:
    """Wraps a vision-capable langchain chat model and produces a Statement."""

    def __init__(self, model):
        # with_structured_output binds the reply schema; called once per model.
        self._model = model.with_structured_output(_VlmStatement)

    def extract(self, pdf: Path | str, page_number: int) -> Statement:
        pdf_path = Path(pdf)
        logger.info("VLM extracting {} page {}", pdf_path.name, page_number)
        png = get_pdf_reader().render_page(pdf, page_number)
        b64 = base64.b64encode(png).decode()

        # Lazy import: keeps `import services.vlm` free of langchain for the
        # core (non-LLM) pipeline; only invoked when the fallback actually runs.
        from langchain_core.messages import HumanMessage
        from ...agents.prompts import statement_extraction_prompt

        message = HumanMessage(content=[
            {"type": "text", "text": statement_extraction_prompt()},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ])
        reply: _VlmStatement = self._model.invoke([message])

        stmt = Statement(
            source_pdf=pdf_path.name,
            statement_pages=[page_number],
            year_current=reply.year_current,
            year_prior=reply.year_prior,
            currency=reply.currency or "AUD",
            units=_UNITS.get((reply.units or "").lower(), Units.ACTUAL),
        )
        for li in reply.line_items:
            stmt.line_items.append(LineItem(
                label_raw=li.label,
                value_current=li.value_current,
                value_prior=li.value_prior,
                note_ref_raw=li.note_ref,
                is_subtotal=li.is_subtotal,
                page=page_number,
                provenance=Provenance(page=page_number, bbox=None, raw_cell_text=li.label),
            ))
        logger.info("VLM parsed {} line item(s) on page {}", len(stmt.line_items), page_number)
        return stmt

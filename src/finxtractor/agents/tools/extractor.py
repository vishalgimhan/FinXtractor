"""Extractor tools — the extraction ladder + normalization as reusable,
LLM-callable steps.

Each tool wraps one piece of what the old `extractor_node` did in a fixed ladder
(`parse_statement` text, `parse_statement` +OCR, note resolution, normalize), so
the agent can choose a tier per page, re-run one on a retry, and stop when a page
reads cleanly. The vision tier is NOT here: a page the text tiers can't read is
left unnormalized and the extractor escalates it to the shared `vlm` graph node.

The tools share an `ExtractorContext`: extractions keep the best raw Statement
per kind in the context (so OCR never discards a cleaner TableFormer parse), and
`normalize_statement` maps it onto the canonical chart. Heavy objects stay in the
context; tools return only compact counts/confidences to the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from langchain_core.tools import tool

from ...parsing.docling_parser import parse_statement, table_confidence
from ...parsing.notes import resolve_line_item_notes
from ...normalize.normalize import normalize
from ...schemas import Statement
from ...schemas.canonical import CanonicalStatement


@dataclass
class ExtractorContext:
    """Shared state for one extraction run: the located pages, the best raw
    extraction per kind (with its confidence), and the normalized canonicals."""
    pdf: Path
    text_layer: str
    pages: dict[str, int]                               # kind -> located page
    raw: dict[str, Statement] = field(default_factory=dict)
    raw_conf: dict[str, float] = field(default_factory=dict)
    canonical: dict[str, CanonicalStatement] = field(default_factory=dict)

    def keep_best(self, kind: str, stmt: Statement, conf: float) -> None:
        """Retain the higher-confidence raw extraction across tiers, so running
        OCR after TableFormer never throws away a cleaner parse."""
        if kind not in self.raw_conf or conf > self.raw_conf[kind]:
            self.raw[kind] = stmt
            self.raw_conf[kind] = conf


def build_extractor_tools(ctx: ExtractorContext) -> list:
    """Build the extractor's tools, all closed over `ctx`."""

    def _extract(kind: str, *, ocr: bool) -> dict:
        if kind not in ctx.pages:
            return {"error": f"no located page for {kind!r}; known: {list(ctx.pages)}"}
        stmt = parse_statement(ctx.pdf, ctx.pages[kind], ocr=ocr)
        conf = table_confidence(stmt)
        ctx.keep_best(kind, stmt, conf)
        return {"kind": kind, "items": len(stmt.line_items),
                "confidence": round(conf, 3), "best_confidence": round(ctx.raw_conf[kind], 3)}

    @tool
    def extract_tableformer(kind: str) -> dict:
        """Extract the `kind` ('income'/'balance') page with TableFormer over the
        text layer — best for digital PDFs. Returns the line-item count and a
        0-1 parse confidence. Pointless on a scan (text_layer == 'none')."""
        return _extract(kind, ocr=False)

    @tool
    def extract_ocr(kind: str) -> dict:
        """Extract the `kind` page with TableFormer+OCR — for scanned/low-text
        pages, or when plain TableFormer parsed few/no rows. The better of the
        two tiers is kept for normalization. Returns item count and confidence."""
        return _extract(kind, ocr=True)

    @tool
    def normalize_statement(kind: str) -> dict:
        """Resolve note references then map the best extraction for `kind` onto
        the canonical chart of accounts. Call once a tier read usable rows.
        Returns the number of canonical accounts mapped."""
        if kind not in ctx.raw:
            return {"error": f"nothing extracted for {kind!r} yet; "
                             "run extract_tableformer / extract_ocr first"}
        raw = ctx.raw[kind]
        resolve_line_item_notes(raw)
        ctx.canonical[kind] = normalize(raw)
        logger.info("Normalized {} -> {} canonical account(s)", kind, len(ctx.canonical[kind].lines))
        return {"kind": kind, "accounts": len(ctx.canonical[kind].lines)}

    return [extract_tableformer, extract_ocr, normalize_statement]

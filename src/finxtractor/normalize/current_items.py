"""LLM classifier for current vs non-current balance-sheet items.

A fallback for when no 'Total current assets/liabilities' subtotal was extracted.
Rather than relying on an exact subtotal label, it hands the already-extracted
balance-sheet rows to the LLM, which (a) decides whether the statement is
classified at all, and (b) if so, names the current rows to sum. A liquidity-
ordered statement (a bank's) is reported as 'unclassified' so the current ratio
is correctly left N/A instead of being fabricated from an arbitrary proxy.

Best-effort and offline-guarded by the caller, like `llm_mapper`.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..schemas.statement import LineItem
from ..services.llm import get_chat_model
from ..agents.prompts import current_items_prompt


class CurrentItemsDecision(BaseModel):
    presentation: str                                  # "classified" | "unclassified"
    current_asset_labels: list[str] = Field(default_factory=list)
    current_liability_labels: list[str] = Field(default_factory=list)


def _fmt(items: list[LineItem]) -> list[str]:
    return [f"{i.label_raw} | {i.value_current}" for i in items]


def classify_current_items(line_items: list[LineItem]) -> CurrentItemsDecision:
    """Ask the LLM to split the balance-sheet rows into current vs non-current.

    Heuristic asset/liability split for the prompt: liabilities are rows whose
    label mentions a liability/equity concept; everything else is treated as an
    asset row. The model gets both lists and the verbatim labels back to choose
    from, so a rough split here only affects prompt grouping, not correctness."""
    liab_words = ("liabilit", "payable", "borrowing", "provision", "equity",
                  "reserve", "capital", "retained")
    assets, liabilities = [], []
    for it in line_items:
        low = it.label_raw.lower()
        (liabilities if any(w in low for w in liab_words) else assets).append(it)

    model = get_chat_model().with_structured_output(CurrentItemsDecision)
    return model.invoke(current_items_prompt(_fmt(assets), _fmt(liabilities)))

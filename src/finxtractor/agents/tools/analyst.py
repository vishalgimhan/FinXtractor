"""Analyst tools — read-only inspection over the already-computed credit report.

The scoring agent never computes a number; it interprets. These tools let it pull
the deterministic ratios, Altman result, composite score, and risk flags on
demand, and trace a ratio back to the source pages/labels behind it (provenance
is already carried on each ratio input, so no graph rebuild is needed).

All returns are compact, JSON-safe (Decimals cast to float) so the figures stay
exact in the model's context.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from langchain_core.tools import tool

from ...scoring.schemas import CreditReport
from ...schemas.canonical import CanonicalStatement


def _f(v) -> float | None:
    """Decimal/None -> float/None for JSON-safe, exact-enough tool output."""
    return float(v) if isinstance(v, Decimal) else v


@dataclass
class AnalystContext:
    """The computed report under assessment, plus the canonical statement (for
    the raw source labels behind each account when tracing provenance)."""
    report: CreditReport
    statement: CanonicalStatement | None = None

    def labels_for(self, account: str) -> list[str]:
        if self.statement is None:
            return []
        line = self.statement.lines.get(account)
        return list(line.source_labels) if line else []


def build_analyst_tools(ctx: AnalystContext) -> list:
    """Build the analyst's read-only inspection tools, closed over `ctx`."""
    report = ctx.report

    @tool
    def get_ratios() -> list:
        """List the computed financial ratios: name, value (or null if undefined),
        formula, and any note (e.g. a zero-denominator reason)."""
        return [{"name": r.name, "value": _f(r.value), "formula": r.formula,
                 "note": r.note} for r in report.ratios]

    @tool
    def get_altman() -> dict:
        """The Altman Z''-score result: components X1-X4, the Z'' value, and the
        distress zone (safe/grey/distress), or empty if not computed."""
        a = report.altman
        if a is None:
            return {}
        return {"x1": _f(a.x1), "x2": _f(a.x2), "x3": _f(a.x3), "x4": _f(a.x4),
                "z_double_prime": _f(a.z_double_prime),
                "zone": a.zone.value if a.zone else None}

    @tool
    def get_composite() -> dict:
        """The composite credit score (0-100), letter grade, per-metric component
        sub-scores, and any notes."""
        c = report.composite
        if c is None:
            return {}
        return {"score_0_100": _f(c.score_0_100), "grade": c.grade,
                "components": {k: _f(v) for k, v in c.components.items()},
                "notes": list(c.notes)}

    @tool
    def list_risk_flags(severity: str | None = None) -> list:
        """Structured risk flags, optionally filtered by severity
        ('high'/'medium'/'low'). Each: code, category, severity, message, and the
        metric/value/prior_value that triggered it."""
        flags = report.risk_flags
        if severity:
            flags = [f for f in flags if f.severity.value == severity.lower()]
        return [{"code": f.code, "category": f.category.value, "severity": f.severity.value,
                 "message": f.message, "metric": f.metric,
                 "value": _f(f.value), "prior_value": _f(f.prior_value)} for f in flags]

    @tool
    def trace_ratio(name: str) -> dict:
        """Trace a ratio (by name) to its provenance: the accounts that fed it,
        each with its value, the source PDF page, and the raw line label(s) it was
        read from — so a concern can cite where it came from (e.g. page 8)."""
        match = next((r for r in report.ratios if r.name == name), None)
        if match is None:
            return {"error": f"no ratio named {name!r}; have {[r.name for r in report.ratios]}"}
        return {"ratio": match.name, "value": _f(match.value), "formula": match.formula,
                "inputs": [{"account": i.account, "value": _f(i.value), "page": i.page,
                            "labels": ctx.labels_for(i.account)} for i in match.inputs]}

    return [get_ratios, get_altman, get_composite, list_risk_flags, trace_ratio]

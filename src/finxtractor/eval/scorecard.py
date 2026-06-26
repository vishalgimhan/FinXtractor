"""Evaluation harness: score an extracted canonical statement against ground truth.

Ground-truth files (data/ground_truth/*.json) are hand-authored in their own
schema; this projects the fields we care about onto our canonical chart and
reports value accuracy + note-linking F1. It is pure/offline — give it a
CanonicalStatement and the loaded ground-truth dict.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal

from ..schemas.canonical import CanonicalStatement

# GT profit_and_loss `label_canonical` -> our canonical account value.
_GT_PNL_TO_ACCOUNT = {
    "total_revenue_net": "revenue",
    "loss_before_income_tax": "profit_before_tax",
    "profit_before_income_tax": "profit_before_tax",
    "income_tax_benefit": "income_tax_expense",
    "income_tax_expense": "income_tax_expense",
    "net_loss": "net_profit",
    "net_profit": "net_profit",
    "interest_expense": "interest_expense",
}
# targeted_balance_sheet keys already named like our accounts.
_GT_BS_ACCOUNTS = {"total_assets", "total_liabilities", "total_equity", "retained_earnings"}

_REL_TOL = Decimal("0.005")     # 0.5% relative tolerance for value matches


def _unit_scale(rounding_unit: str) -> Decimal:
    u = (rounding_unit or "").lower()
    if "million" in u:
        return Decimal(1_000_000)
    if "thousand" in u:
        return Decimal(1_000)
    return Decimal(1)


def _dec(value) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _fy_keys(extracted: dict) -> list[str]:
    """FY keys newest-first, e.g. ['FY2024', 'FY2023'] -> (current, prior)."""
    return sorted((k for k in extracted if k.upper().startswith("FY")), reverse=True)


def _gt_values(extracted: dict, scale: Decimal) -> tuple[Decimal | None, Decimal | None]:
    fys = _fy_keys(extracted)

    def val(i: int) -> Decimal | None:
        if i >= len(fys):
            return None
        d = _dec(extracted[fys[i]].get("parsed_value"))
        return None if d is None else d * scale

    return val(0), val(1)


def ground_truth_to_canonical(gt: dict) -> dict[str, dict]:
    """Project a ground-truth file onto {account: {current, prior, note_refs}},
    with values scaled to absolute units (matching our canonical statement)."""
    scale = _unit_scale(gt.get("statement_metadata", {}).get("rounding_unit", ""))
    out: dict[str, dict] = {}
    for line in gt.get("profit_and_loss", []):
        acct = _GT_PNL_TO_ACCOUNT.get(line.get("label_canonical"))
        if not acct:
            continue
        cur, pri = _gt_values(line.get("extracted_data", {}), scale)
        out[acct] = {"current": cur, "prior": pri, "note_refs": list(line.get("note_refs", []))}
    for key, line in gt.get("targeted_balance_sheet", {}).items():
        if key in _GT_BS_ACCOUNTS:
            cur, pri = _gt_values(line.get("extracted_data", {}), scale)
            out[key] = {"current": cur, "prior": pri, "note_refs": list(line.get("note_refs", []))}
    return out


def _close(expected: Decimal | None, actual: Decimal | None) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if expected == actual:
        return True
    return abs(expected - actual) <= _REL_TOL * max(abs(expected), abs(actual))


@dataclass
class FieldResult:
    account: str
    period: str                 # "current" | "prior"
    expected: Decimal | None
    actual: Decimal | None
    ok: bool


@dataclass
class Scorecard:
    source_pdf: str = ""
    fields: list[FieldResult] = field(default_factory=list)
    note_tp: int = 0
    note_fp: int = 0
    note_fn: int = 0

    @property
    def value_accuracy(self) -> float:
        return (sum(1 for f in self.fields if f.ok) / len(self.fields)) if self.fields else 0.0

    @property
    def mismatches(self) -> list[FieldResult]:
        return [f for f in self.fields if not f.ok]

    @property
    def note_precision(self) -> float:
        denom = self.note_tp + self.note_fp
        return self.note_tp / denom if denom else 1.0

    @property
    def note_recall(self) -> float:
        denom = self.note_tp + self.note_fn
        return self.note_tp / denom if denom else 1.0

    @property
    def note_f1(self) -> float:
        p, r = self.note_precision, self.note_recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0

    def render(self) -> str:
        ok = sum(1 for f in self.fields if f.ok)
        lines = [
            f"Scorecard for {self.source_pdf or '?'}",
            f"  value accuracy : {ok}/{len(self.fields)} = {self.value_accuracy:.1%}",
            f"  note linking   : P={self.note_precision:.2f} R={self.note_recall:.2f} "
            f"F1={self.note_f1:.2f} (tp={self.note_tp} fp={self.note_fp} fn={self.note_fn})",
        ]
        if self.mismatches:
            lines.append("  mismatches:")
            for m in self.mismatches:
                lines.append(f"    {m.account}.{m.period}: expected {m.expected}, got {m.actual}")
        return "\n".join(lines)


def score(canonical: CanonicalStatement, gt: dict) -> Scorecard:
    """Compare an extracted canonical statement against ground truth."""
    gt_canon = ground_truth_to_canonical(gt)
    card = Scorecard(source_pdf=canonical.source_pdf)
    for acct, gv in gt_canon.items():
        line = canonical.lines.get(acct)
        for period in ("current", "prior"):
            expected = gv[period]
            actual = getattr(line, f"value_{period}") if line else None
            card.fields.append(FieldResult(acct, period, expected, actual, _close(expected, actual)))
        gt_notes = {str(n) for n in gv["note_refs"]}
        our_notes = {n.key() for n in line.note_refs} if line else set()
        card.note_tp += len(gt_notes & our_notes)
        card.note_fp += len(our_notes - gt_notes)
        card.note_fn += len(gt_notes - our_notes)
    return card

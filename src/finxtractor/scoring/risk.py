"""Rule-based risk-flag detection for the credit report.

Turns a scored statement into structured, analyst-readable `RiskFlag`s in three
families:

  1. threshold breaches on the headline ratios + the Altman zone (current period),
  2. year-on-year deterioration, using the prior-year column we already capture,
  3. data-quality issues surfaced from the cross-foot validation checks.

Cut-offs are documented module constants (as in scoring/composite.py), not magic
numbers, so the methodology is inspectable and tunable. Note-disclosure and
off-balance-sheet anomalies are out of scope here — they need note-table semantics
beyond the canonical chart and would be a separate, heuristic pass.
"""
from __future__ import annotations
from decimal import Decimal
from typing import Optional

from ..schemas.canonical import CanonicalStatement, CanonicalAccount as A
from ..validate.results import CheckResult, CheckStatus
from .schemas import (
    Ratio, AltmanResult, Zone, RiskFlag, RiskCategory as Cat, RiskSeverity as Sev,
)
from .ratios import compute_ratios

# --- current-period thresholds (mirror the composite bands' intent) ---
_MARGIN_FLOOR = Decimal("0")        # net margin below this = loss-making
_CURRENT_FLOOR = Decimal("1.0")     # current assets should cover current liabilities
_COVERAGE_WEAK = Decimal("1.5")     # EBIT/interest below this = thin cushion
_COVERAGE_CRIT = Decimal("1.0")     # ...below this = cannot cover interest
_DE_HIGH = Decimal("2.0")           # debt/equity above this = heavily leveraged

# --- year-on-year materiality ---
_REV_DROP = Decimal("0.10")         # revenue down >10% YoY = material
_NP_DROP = Decimal("0.20")          # net profit down >20% YoY = material
_MARGIN_COMPRESS = Decimal("0.05")  # net margin down >5 percentage points YoY
_DE_RISE = Decimal("0.25")          # debt/equity up >25% relative YoY
_CURRENT_FALL = Decimal("0.25")     # current ratio down >25% relative YoY


def _val(stmt: CanonicalStatement, account: A, year: str) -> Optional[Decimal]:
    line = stmt.get(account)
    return getattr(line, f"value_{year}") if line else None


def _by_name(ratios: list[Ratio]) -> dict[str, Optional[Decimal]]:
    return {r.name: r.value for r in ratios}


def _threshold_flags(ratios: list[Ratio], altman: Optional[AltmanResult]) -> list[RiskFlag]:
    flags: list[RiskFlag] = []
    r = _by_name(ratios)

    npm = r.get("net_profit_margin")
    if npm is not None and npm < _MARGIN_FLOOR:
        flags.append(RiskFlag(
            code="negative_margin", category=Cat.PROFITABILITY, severity=Sev.HIGH,
            metric="net_profit_margin", value=npm,
            message=f"Negative profit margin ({float(npm):.1%}): operating at a net loss this period."))

    cr = r.get("current_ratio")
    if cr is not None and cr < _CURRENT_FLOOR:
        flags.append(RiskFlag(
            code="weak_current_ratio", category=Cat.LIQUIDITY, severity=Sev.MEDIUM,
            metric="current_ratio", value=cr,
            message=f"Weak current ratio ({float(cr):.2f}): current liabilities exceed current assets — liquidity pressure."))

    ic = r.get("interest_coverage")
    if ic is not None and ic < _COVERAGE_WEAK:
        sev = Sev.HIGH if ic < _COVERAGE_CRIT else Sev.MEDIUM
        flags.append(RiskFlag(
            code="fragile_interest_coverage", category=Cat.COVERAGE, severity=sev,
            metric="interest_coverage", value=ic,
            message=f"Fragile interest coverage ({float(ic):.2f}x): EBIT is insufficient to comfortably service interest."))

    de = r.get("debt_to_equity")
    if de is not None and de > _DE_HIGH:
        flags.append(RiskFlag(
            code="high_leverage", category=Cat.LEVERAGE, severity=Sev.MEDIUM,
            metric="debt_to_equity", value=de,
            message=f"High debt-to-equity ({float(de):.2f}): heavily leveraged capital structure."))

    if altman is not None and altman.zone == Zone.DISTRESS:
        flags.append(RiskFlag(
            code="altman_distress", category=Cat.SOLVENCY, severity=Sev.HIGH,
            metric="altman_zscore", value=altman.z_double_prime,
            message="Altman distress zone: elevated insolvency risk — restructuring or credit limits advised."))
    elif altman is not None and altman.zone == Zone.GREY:
        flags.append(RiskFlag(
            code="altman_grey", category=Cat.SOLVENCY, severity=Sev.MEDIUM,
            metric="altman_zscore", value=altman.z_double_prime,
            message="Altman grey zone: unstable positioning — warrants close tracking."))

    return flags


def _trend_flags(stmt: CanonicalStatement, ratios: list[Ratio]) -> list[RiskFlag]:
    """Year-on-year deterioration, using the prior-year column we already capture."""
    flags: list[RiskFlag] = []

    rev_c, rev_p = _val(stmt, A.REVENUE, "current"), _val(stmt, A.REVENUE, "prior")
    if rev_c is not None and rev_p is not None and rev_p > 0:
        drop = (rev_p - rev_c) / rev_p
        if drop > _REV_DROP:
            flags.append(RiskFlag(
                code="revenue_decline", category=Cat.TREND, severity=Sev.MEDIUM,
                metric="revenue", value=rev_c, prior_value=rev_p,
                message=f"Revenue fell {float(drop):.1%} year-on-year ({rev_p:,} → {rev_c:,})."))

    np_c, np_p = _val(stmt, A.NET_PROFIT, "current"), _val(stmt, A.NET_PROFIT, "prior")
    if np_c is not None and np_p is not None:
        if np_p > 0 and np_c <= 0:
            flags.append(RiskFlag(
                code="swing_to_loss", category=Cat.TREND, severity=Sev.HIGH,
                metric="net_profit", value=np_c, prior_value=np_p,
                message=f"Swung from a prior-year profit ({np_p:,}) to a current-year loss ({np_c:,})."))
        elif np_p > 0 and (np_p - np_c) / np_p > _NP_DROP:
            flags.append(RiskFlag(
                code="net_profit_decline", category=Cat.TREND, severity=Sev.MEDIUM,
                metric="net_profit", value=np_c, prior_value=np_p,
                message=f"Net profit fell {float((np_p - np_c) / np_p):.1%} year-on-year ({np_p:,} → {np_c:,})."))

    # Ratio-level trends: compare the same metric current vs prior.
    cur = _by_name(ratios)
    prior = _by_name(compute_ratios(stmt, "prior"))

    npm_c, npm_p = cur.get("net_profit_margin"), prior.get("net_profit_margin")
    if npm_c is not None and npm_p is not None and (npm_p - npm_c) > _MARGIN_COMPRESS:
        flags.append(RiskFlag(
            code="margin_compression", category=Cat.TREND, severity=Sev.MEDIUM,
            metric="net_profit_margin", value=npm_c, prior_value=npm_p,
            message=f"Net margin compressed {float(npm_p - npm_c):.1%} year-on-year ({float(npm_p):.1%} → {float(npm_c):.1%})."))

    de_c, de_p = cur.get("debt_to_equity"), prior.get("debt_to_equity")
    if de_c is not None and de_p is not None and de_p > 0 and (de_c - de_p) / de_p > _DE_RISE:
        flags.append(RiskFlag(
            code="leverage_increase", category=Cat.TREND, severity=Sev.MEDIUM,
            metric="debt_to_equity", value=de_c, prior_value=de_p,
            message=f"Leverage rose {float((de_c - de_p) / de_p):.0%} year-on-year (D/E {float(de_p):.2f} → {float(de_c):.2f})."))

    cr_c, cr_p = cur.get("current_ratio"), prior.get("current_ratio")
    if cr_c is not None and cr_p is not None and cr_p > 0 and (cr_p - cr_c) / cr_p > _CURRENT_FALL:
        flags.append(RiskFlag(
            code="liquidity_decline", category=Cat.TREND, severity=Sev.MEDIUM,
            metric="current_ratio", value=cr_c, prior_value=cr_p,
            message=f"Current ratio fell {float((cr_p - cr_c) / cr_p):.0%} year-on-year ({float(cr_p):.2f} → {float(cr_c):.2f})."))

    return flags


def _data_quality_flags(checks: Optional[list[CheckResult]]) -> list[RiskFlag]:
    """Surface failed cross-foot checks: a failed identity means the extracted
    figures don't reconcile, so any score built on them is suspect."""
    flags: list[RiskFlag] = []
    for c in checks or []:
        if c.status == CheckStatus.FAIL:
            flags.append(RiskFlag(
                code=f"check_{c.name}", category=Cat.DATA_QUALITY, severity=Sev.MEDIUM,
                metric=c.name,
                message=f"Validation check '{c.name}' failed: {c.message}"))
    return flags


def compute_risk(stmt: CanonicalStatement, ratios: list[Ratio],
                 altman: Optional[AltmanResult],
                 checks: Optional[list[CheckResult]] = None) -> list[RiskFlag]:
    """All risk flags for one company: thresholds + YoY trend + data quality."""
    return (_threshold_flags(ratios, altman)
            + _trend_flags(stmt, ratios)
            + _data_quality_flags(checks))

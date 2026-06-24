from decimal import Decimal
from pathlib import Path

from loguru import logger

from ..schemas import Statement, Units
from ..schemas.canonical import CanonicalAccount, CanonicalLine, CanonicalStatement
from ..parsing.docling_parser import parse_all_tables   # all tables on a page -> Statement
from ..parsing.routing import rank_balance_sheet_pages
from ..parsing.text import extract_pages
from .mapper import map_label
from .llm_mapper import map_label_llm

_SCALE = {
    Units.ACTUAL: Decimal(1),
    Units.THOUSANDS: Decimal(1_000),
    Units.MILLIONS: Decimal(1_000_000),
}

# Accounts conventionally printed as positives that represent outflows.
_EXPENSE_ACCOUNTS = {
    CanonicalAccount.COST_OF_SALES,
    CanonicalAccount.OPERATING_EXPENSES,
    CanonicalAccount.INTEREST_EXPENSE,
    CanonicalAccount.INCOME_TAX_EXPENSE,
}


def _sign_for(account: CanonicalAccount, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    # Store expenses as positive magnitudes; the scoring layer knows they subtract.
    if account in _EXPENSE_ACCOUNTS:
        return abs(value)
    return value


def _to_decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))          # via str() — NEVER Decimal(float)


def _scaled(value: Decimal | None, units: Units) -> Decimal | None:
    if value is None:
        return None
    return value * _SCALE[units]


def _resolve_account(
    label: str, is_subtotal: bool, use_llm: bool
) -> tuple[CanonicalAccount | None, str]:
    """Label mapping: alias -> fuzzy -> (optional) LLM. The LLM tier is opt-in
    and only considers subtotal rows (the standard statement lines), so detail
    components aren't force-fit; it's also guarded against an offline model."""
    result = map_label(label)
    if result.account is not None:
        return result.account, result.method
    if not (use_llm and is_subtotal):
        return None, "unmapped"
    try:
        account, _reason = map_label_llm(label)
    except Exception as exc:                       # model offline / call failed
        logger.warning("LLM label mapping failed for {!r}: {}", label, exc)
        account = None
    return account, ("llm" if account else "unmapped")


def normalize(stmt: Statement, use_llm: bool = False) -> CanonicalStatement:
    cs = CanonicalStatement(
        source_pdf=stmt.source_pdf,
        year_current=stmt.year_current,
        year_prior=stmt.year_prior,
        currency=stmt.currency,
    )
    from_subtotal: dict[str, bool] = {}   # whether the stored value came from a subtotal row
    for item in stmt.line_items:
        account, method = _resolve_account(item.label_raw, item.is_subtotal, use_llm)
        if account is None:
            continue                                # truly unmappable
        cur = _sign_for(account, _scaled(_to_decimal(item.value_current), stmt.units))
        pri = _sign_for(account, _scaled(_to_decimal(item.value_prior), stmt.units))

        key = account.value
        if key in cs.lines:                         # account already seen
            existing = cs.lines[key]
            existing.source_labels.append(item.label_raw)
            # A subtotal (the real total line) wins over a detail component.
            if item.is_subtotal and not from_subtotal.get(key, False):
                existing.value_current, existing.value_prior = cur, pri
                existing.mapped_by = method
                from_subtotal[key] = True
            continue
        cs.lines[key] = CanonicalLine(
            account=account, value_current=cur, value_prior=pri,
            source_labels=[item.label_raw], mapped_by=method,
        )
        from_subtotal[key] = item.is_subtotal
    return cs


# --- targeted balance-sheet pull (Phase 4 scope extension) ------------------

def _bs_page(pdf: Path | str, override: int | None) -> int:
    if override:
        return override
    ranked = rank_balance_sheet_pages(extract_pages(pdf))
    if not ranked:
        raise ValueError("No balance-sheet page found; pass an explicit page")
    return ranked[0]


def pull_balance_sheet(
    pdf: Path | str, page: int | None = None, use_llm: bool = False
) -> CanonicalStatement:
    """Targeted balance-sheet pull: parse ALL tables on the BS page and normalize,
    picking up current/total assets, liabilities, equity, retained earnings even
    when the totals sit in a different table than the densest one."""
    stmt = parse_all_tables(pdf, _bs_page(pdf, page))
    return normalize(stmt, use_llm=use_llm)


def merge(income: CanonicalStatement, balance: CanonicalStatement) -> CanonicalStatement:
    """Combine income-statement and balance-sheet canonical lines into one
    statement. Income metadata wins; balance lines fill accounts income lacks."""
    merged = income.model_copy(deep=True)
    for key, line in balance.lines.items():
        if key not in merged.lines:
            merged.lines[key] = line
    return merged

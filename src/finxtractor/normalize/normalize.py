from decimal import Decimal
from pathlib import Path

from loguru import logger

from ..schemas import Statement, Units
from ..schemas.canonical import CanonicalAccount, CanonicalLine, CanonicalStatement
from ..parsing.docling_parser import parse_income_statement   # generic table->Statement
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


def _resolve_account(label: str) -> tuple[CanonicalAccount | None, str]:
    """Three-tier label mapping: alias -> fuzzy -> LLM. The LLM tier is guarded
    so a missing/offline model degrades to 'unmapped' instead of crashing."""
    result = map_label(label)
    if result.account is not None:
        return result.account, result.method
    try:
        account, _reason = map_label_llm(label)
    except Exception as exc:                       # model offline / call failed
        logger.warning("LLM label mapping failed for {!r}: {}", label, exc)
        account = None
    return account, ("llm" if account else "unmapped")


def normalize(stmt: Statement) -> CanonicalStatement:
    cs = CanonicalStatement(
        source_pdf=stmt.source_pdf,
        year_current=stmt.year_current,
        year_prior=stmt.year_prior,
        currency=stmt.currency,
    )
    for item in stmt.line_items:
        account, method = _resolve_account(item.label_raw)
        if account is None:
            continue                                # truly unmappable
        cur = _sign_for(account, _scaled(_to_decimal(item.value_current), stmt.units))
        pri = _sign_for(account, _scaled(_to_decimal(item.value_prior), stmt.units))

        key = account.value
        if key in cs.lines:                         # account already filled
            cs.lines[key].source_labels.append(item.label_raw)
            continue
        cs.lines[key] = CanonicalLine(
            account=account, value_current=cur, value_prior=pri,
            source_labels=[item.label_raw], mapped_by=method,
        )
    return cs


# --- targeted balance-sheet pull (Phase 4 scope extension) ------------------

def _bs_page(pdf: Path | str, override: int | None) -> int:
    if override:
        return override
    ranked = rank_balance_sheet_pages(extract_pages(pdf))
    if not ranked:
        raise ValueError("No balance-sheet page found; pass an explicit page")
    return ranked[0]


def pull_balance_sheet(pdf: Path | str, page: int | None = None) -> CanonicalStatement:
    """Parse the balance-sheet page and normalize it (same table parser, different
    page) to pick up current/total assets, liabilities, equity, retained earnings."""
    stmt = parse_income_statement(pdf, _bs_page(pdf, page))
    return normalize(stmt)


def merge(income: CanonicalStatement, balance: CanonicalStatement) -> CanonicalStatement:
    """Combine income-statement and balance-sheet canonical lines into one
    statement. Income metadata wins; balance lines fill accounts income lacks."""
    merged = income.model_copy(deep=True)
    for key, line in balance.lines.items():
        if key not in merged.lines:
            merged.lines[key] = line
    return merged

from decimal import Decimal

from loguru import logger

from ..schemas import Statement, Units
from ..schemas.canonical import CanonicalAccount, CanonicalLine, CanonicalStatement
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


def _derive_ebit(cs: CanonicalStatement) -> None:
    """Derive EBIT analytically when no operating-profit line was mapped.

    Many statements never print an EBIT/operating-profit subtotal (or print one
    under a label we don't recognise), which would leave interest_coverage and
    Altman X3 undefined. EBIT is recoverable from the identity
    EBIT = profit_before_tax + interest_expense: interest is stored as a positive
    magnitude, so adding it back to PBT (already net of interest) reconstructs the
    pre-interest figure. Only fills when EBIT is absent or has no current value —
    a real extracted EBIT always wins."""
    existing = cs.get(CanonicalAccount.EBIT)
    if existing is not None and existing.value_current is not None:
        return
    pbt = cs.get(CanonicalAccount.PROFIT_BEFORE_TAX)
    interest = cs.get(CanonicalAccount.INTEREST_EXPENSE)
    if pbt is None or interest is None:
        return

    def _add(a: Decimal | None, b: Decimal | None) -> Decimal | None:
        return None if a is None or b is None else a + b

    cur = _add(pbt.value_current, interest.value_current)
    pri = _add(pbt.value_prior, interest.value_prior)
    if cur is None and pri is None:
        return
    cs.lines[CanonicalAccount.EBIT.value] = CanonicalLine(
        account=CanonicalAccount.EBIT,
        value_current=cur,
        value_prior=pri,
        source_labels=["(derived: profit_before_tax + interest_expense)"],
        mapped_by="derived",
    )
    logger.info("Derived EBIT for {} (no operating-profit line): current={}, prior={}",
                cs.source_pdf, cur, pri)


def _resolve_current_items(stmt: Statement, cs: CanonicalStatement, use_llm: bool) -> None:
    """Fill current_assets / current_liabilities when no subtotal was mapped.

    Mode 1 (reported subtotal) is handled by the alias mapper in the main loop —
    if both accounts already carry a value, there is nothing to do. Otherwise,
    and only with the LLM tier enabled, classify the extracted balance-sheet rows:
    Mode 2 (classified, no subtotal) sums the rows the model tags as current;
    Mode 3 (unclassified/liquidity-ordered, e.g. a bank) records the accounts
    valueless with mapped_by='unclassified' so the current ratio reads N/A rather
    than being fabricated from an arbitrary proxy. Offline-guarded like the LLM
    label mapper."""
    ca, cl = cs.get(CanonicalAccount.CURRENT_ASSETS), cs.get(CanonicalAccount.CURRENT_LIABILITIES)
    if (ca and ca.value_current is not None) and (cl and cl.value_current is not None):
        return
    # Only meaningful on a balance-sheet-like statement.
    if not (cs.get(CanonicalAccount.TOTAL_ASSETS) or cs.get(CanonicalAccount.TOTAL_LIABILITIES)):
        return
    if not use_llm:
        return
    try:
        from .current_items import classify_current_items
        decision = classify_current_items(stmt.line_items)
    except Exception as exc:                       # model offline / call failed
        logger.warning("Current-items classifier unavailable ({}); current ratio left N/A", exc)
        return

    if decision.presentation.lower().startswith("unclass"):
        for acct in (CanonicalAccount.CURRENT_ASSETS, CanonicalAccount.CURRENT_LIABILITIES):
            if cs.get(acct) is None:
                cs.lines[acct.value] = CanonicalLine(
                    account=acct, value_current=None, value_prior=None,
                    source_labels=[], mapped_by="unclassified")
        logger.info("Balance sheet is unclassified (liquidity-ordered); current ratio N/A for {}",
                    cs.source_pdf)
        return

    def _sum(labels: list[str], acct: CanonicalAccount) -> None:
        existing = cs.get(acct)
        if existing is not None and existing.value_current is not None:
            return                                  # a reported subtotal wins
        wanted = {l.strip().lower() for l in labels}
        rows = [it for it in stmt.line_items
                if it.label_raw.strip().lower() in wanted and not it.is_subtotal]
        if not rows:
            return
        cur = sum((_scaled(_to_decimal(r.value_current), stmt.units) or Decimal(0)) for r in rows)
        pris = [_scaled(_to_decimal(r.value_prior), stmt.units) for r in rows]
        pri = sum((v or Decimal(0)) for v in pris) if any(v is not None for v in pris) else None
        cs.lines[acct.value] = CanonicalLine(
            account=acct, value_current=cur, value_prior=pri,
            source_labels=[r.label_raw for r in rows], mapped_by="llm_classified")
        logger.info("Classified {} from {} row(s) for {} -> {}",
                    acct.value, len(rows), cs.source_pdf, cur)

    _sum(decision.current_asset_labels, CanonicalAccount.CURRENT_ASSETS)
    _sum(decision.current_liability_labels, CanonicalAccount.CURRENT_LIABILITIES)


def _merge_note_refs(dst: list, src: list) -> None:
    """Append src note refs to dst, deduped by canonical key."""
    seen = {r.key() for r in dst}
    for r in src:
        if r.key() not in seen:
            dst.append(r)
            seen.add(r.key())


def normalize(stmt: Statement, use_llm: bool = False) -> CanonicalStatement:
    logger.info("Normalizing {} line item(s) from {} (llm={})", len(stmt.line_items), stmt.source_pdf, use_llm)
    cs = CanonicalStatement(
        source_pdf=stmt.source_pdf,
        statement_pages=stmt.statement_pages,
        year_current=stmt.year_current,
        year_prior=stmt.year_prior,
        currency=stmt.currency,
        units=stmt.units,
        sign_convention=stmt.sign_convention,
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
            _merge_note_refs(existing.note_refs, item.note_refs)
            # A subtotal (the real total line) wins over a detail component.
            if item.is_subtotal and not from_subtotal.get(key, False):
                existing.value_current, existing.value_prior = cur, pri
                existing.mapped_by = method
                from_subtotal[key] = True
            continue
        cs.lines[key] = CanonicalLine(
            account=account, 
            value_current=cur, 
            value_prior=pri,
            source_labels=[item.label_raw], 
            note_refs=list(item.note_refs), 
            mapped_by=method,
            provenance=item.provenance,
        )
        from_subtotal[key] = item.is_subtotal
    _resolve_current_items(stmt, cs, use_llm)
    _derive_ebit(cs)
    logger.info("Normalization produced {} canonical line(s) for {}", len(cs.lines), stmt.source_pdf)
    return cs


def merge_raw(income: Statement, *others: Statement) -> Statement:
    """Combine raw statements (line items + provenance) into one — income first so
    its metadata leads. The single explainability substrate `build_graph` consumes,
    replacing per-page re-extraction."""
    merged = income.model_copy(deep=True)
    for other in others:
        merged.line_items.extend(other.line_items)
        merged.statement_pages = sorted(set(merged.statement_pages) | set(other.statement_pages))
    return merged


def merge(income: CanonicalStatement, balance: CanonicalStatement) -> CanonicalStatement:
    """Combine income-statement and balance-sheet canonical lines into one
    statement. Income metadata wins; balance lines fill accounts income lacks."""
    merged = income.model_copy(deep=True)
    merged.statement_pages = sorted(set(income.statement_pages) | set(balance.statement_pages))
    added = 0
    for key, line in balance.lines.items():
        if key not in merged.lines:
            merged.lines[key] = line
            added += 1
    logger.info("Merged canonical statements: kept {} income line(s), added {} balance line(s)", len(income.lines), added)
    return merged

from pathlib import Path
from decimal import Decimal

from loguru import logger

from ..schemas.canonical import CanonicalStatement, CanonicalAccount
from .checks import run_all_checks
from .results import CheckResult, CheckStatus

from ..config import get_param
from ..parsing.statements import extract_canonical
from ..normalize.normalize import merge

# Which accounts live on which statement — tells us which page to re-extract.
_INCOME_ACCOUNTS = {"revenue", "cost_of_sales", "gross_profit", "operating_expenses",
                    "ebit", "interest_expense", "profit_before_tax",
                    "income_tax_expense", "net_profit"}
_BALANCE_ACCOUNTS = {"current_assets", "total_assets", "current_liabilities",
                     "total_liabilities", "total_equity", "retained_earnings"}


def _failing_region(failed: list[CheckResult]) -> str:
    accounts = {a for c in failed for a in c.accounts}
    if accounts & _BALANCE_ACCOUNTS and not (accounts & _INCOME_ACCOUNTS):
        return "balance"
    if accounts & _INCOME_ACCOUNTS:
        return "income"
    return "income"

def _reextract(pdf: Path | str, region: str, income_page: int,
               bs_page: int | None) -> CanonicalStatement:
    """Second attempt at the failing region. A real retry should *change something* —
    e.g. ACCURATE TableFormer mode, or the VLM fork once armed — not just repeat."""
    if region == "balance":
        logger.info("Retrying balance-sheet extraction for {}", pdf)
        return extract_canonical(pdf, bs_page)
    logger.info("Retrying income-statement extraction for {} page {}", pdf, income_page)
    return extract_canonical(pdf, income_page)

def validate_with_retry(pdf: Path | str, stmt: CanonicalStatement,
                        income_page: int, bs_page: int | None = None,
                        max_retries: int | None = None) -> tuple[CanonicalStatement, list[CheckResult], int]:
    if max_retries is None:
        max_retries = get_param("validation", "max_retries", default=2)
    logger.info("Validating {} with up to {} retry(ies)", pdf, max_retries)
    checks = run_all_checks(stmt)
    retries = 0
    while retries < max_retries:
        failed = [c for c in checks if c.status == CheckStatus.FAIL]
        if not failed:
            break
        retries += 1
        region = _failing_region(failed)
        logger.warning("Validation failed in {} region; retry {} of {}", region, retries, max_retries)
        candidate = _reextract(pdf, region, income_page, bs_page)
        candidate = merge(stmt, candidate) if region == "balance" else \
                    merge(candidate, stmt)
        new_checks = run_all_checks(candidate)
        new_failed = sum(1 for c in new_checks if c.status == CheckStatus.FAIL)
        if new_failed < len(failed):          # only accept a genuine improvement
            logger.info("Retry improved validation from {} failures to {}", len(failed), new_failed)
            stmt, checks = candidate, new_checks
        else:
            logger.info("Retry did not improve validation; stopping")
            break                              # no improvement -> stop, let HITL handle it
    logger.info("Validation complete for {} after {} retry(ies)", pdf, retries)
    return stmt, checks, retries
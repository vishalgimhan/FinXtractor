from decimal import Decimal
from ..config import get_param
from ..schemas.canonical import CanonicalAccount as A, CanonicalStatement
from .results import CheckResult, CheckStatus


def _tolerance(*values: Decimal) -> Decimal:
    # Relative slack for rounding (default 0.5% of the larger magnitude), floored
    # at a small absolute. Both come from config/param.yaml (validation.*).
    rel = Decimal(str(get_param("validation", "rel_tolerance", default=0.005)))
    floor = Decimal(str(get_param("validation", "abs_tolerance_floor", default=1000)))
    mag = max((abs(v) for v in values if v is not None), default=Decimal(0))
    return max(mag * rel, floor)

#Value fetcher
def _val(stmt: CanonicalStatement, account: A, year: str = "current") -> Decimal | None:
    line = stmt.get(account)
    if line is None:
        return None
    return getattr(line, f"value_{year}")

def check_income_identity(stmt: CanonicalStatement, year: str = "current") -> CheckResult:
    rev = _val(stmt, A.REVENUE, year)
    cos = _val(stmt, A.COST_OF_SALES, year)
    opex = _val(stmt, A.OPERATING_EXPENSES, year)
    interest = _val(stmt, A.INTEREST_EXPENSE, year)
    tax = _val(stmt, A.INCOME_TAX_EXPENSE, year)
    net = _val(stmt, A.NET_PROFIT, year)

    if rev is None or net is None:
        return CheckResult(name="income_identity", status=CheckStatus.SKIP,
                           accounts=["revenue", "net_profit"],
                           message="missing revenue or net profit")
    # The identity is only meaningful when the full expense breakdown was
    # canonicalized. Many statements (e.g. financial institutions, or a revenue
    # line already reported net of interest) map only a sparse subset, which
    # would make revenue - expenses != net spuriously. Skip rather than false-fail.
    if cos is None and opex is None:
        return CheckResult(name="income_identity", status=CheckStatus.SKIP,
                           accounts=["revenue", "net_profit"],
                           message="expense breakdown not canonicalized; skipping full identity")

    expenses = sum((x for x in (cos, opex, interest, tax) if x is not None), Decimal(0))
    expected = rev - expenses                      # expenses stored positive (Phase 4)
    diff = net - expected
    tol = _tolerance(rev, net)
    status = CheckStatus.PASS if abs(diff) <= tol else CheckStatus.FAIL
    return CheckResult(
        name="income_identity", status=status,
        expected=expected, actual=net, difference=diff, tolerance=tol,
        accounts=["revenue", "net_profit", "cost_of_sales",
                  "operating_expenses", "interest_expense", "income_tax_expense"],
        message=(f"revenue {rev} - expenses {expenses} = {expected}, "
                 f"but net profit = {net} (diff {diff}, tol {tol})"),
    )


def check_pretax_to_net(stmt: CanonicalStatement, year: str = "current") -> CheckResult:
    """Pre-tax to net bridge: the gap between pre-tax and net profit should equal
    the income-tax magnitude. Sign-agnostic, since tax is stored as a positive
    magnitude (expense vs. benefit is ambiguous after that), so this holds for
    both profit-makers and loss-makers with a tax benefit."""
    pbt = _val(stmt, A.PROFIT_BEFORE_TAX, year)
    tax = _val(stmt, A.INCOME_TAX_EXPENSE, year)
    net = _val(stmt, A.NET_PROFIT, year)
    if pbt is None or net is None or tax is None:
        return CheckResult(name="pretax_to_net", status=CheckStatus.SKIP,
                           accounts=["profit_before_tax", "income_tax_expense", "net_profit"],
                           message="missing pre-tax, tax, or net profit")
    gap = abs(net - pbt)
    diff = gap - abs(tax)
    tol = _tolerance(pbt, net)
    status = CheckStatus.PASS if abs(diff) <= tol else CheckStatus.FAIL
    return CheckResult(
        name="pretax_to_net", status=status,
        expected=abs(tax), actual=gap, difference=diff, tolerance=tol,
        accounts=["profit_before_tax", "income_tax_expense", "net_profit"],
        message=(f"|net {net} - pre-tax {pbt}| = {gap} vs tax magnitude {abs(tax)} "
                 f"(diff {diff}, tol {tol})"),
    )

def check_balance_identity(stmt: CanonicalStatement, year: str = "current") -> CheckResult:
    assets = _val(stmt, A.TOTAL_ASSETS, year)
    liabilities = _val(stmt, A.TOTAL_LIABILITIES, year)
    equity = _val(stmt, A.TOTAL_EQUITY, year)

    if assets is None or liabilities is None or equity is None:
        return CheckResult(name="balance_identity", status=CheckStatus.SKIP,
                           accounts=["total_assets", "total_liabilities", "total_equity"],
                           message="missing a balance-sheet total")

    expected = liabilities + equity
    diff = assets - expected
    tol = _tolerance(assets)
    status = CheckStatus.PASS if abs(diff) <= tol else CheckStatus.FAIL
    return CheckResult(
        name="balance_identity", status=status,
        expected=expected, actual=assets, difference=diff, tolerance=tol,
        accounts=["total_assets", "total_liabilities", "total_equity"],
        message=f"assets {assets} vs liabilities+equity {expected} (diff {diff}, tol {tol})",
    )

# subtotal roll-up check
def check_note_rollup(stmt: CanonicalStatement, total: A,
                      components: list[A], year: str = "current") -> CheckResult:
    total_v = _val(stmt, total, year)
    parts = [(_val(stmt, c, year)) for c in components]
    present = [p for p in parts if p is not None]
    if total_v is None or not present:
        return CheckResult(name=f"rollup_{total.value}", status=CheckStatus.SKIP,
                           accounts=[total.value], message="missing total or components")
    summed = sum(present, Decimal(0))
    diff = total_v - summed
    tol = _tolerance(total_v)
    status = CheckStatus.PASS if abs(diff) <= tol else CheckStatus.FAIL
    return CheckResult(
        name=f"rollup_{total.value}", status=status,
        expected=summed, actual=total_v, difference=diff, tolerance=tol,
        accounts=[total.value] + [c.value for c in components],
        message=f"{total.value} {total_v} vs components {summed} (diff {diff}, tol {tol})",
    )

def run_all_checks(stmt: CanonicalStatement, year: str = "current") -> list[CheckResult]:
    return [
        check_income_identity(stmt, year),
        check_pretax_to_net(stmt, year),
        check_balance_identity(stmt, year),
        # add report-specific roll-ups here, e.g.:
        # check_note_rollup(stmt, A.GROSS_PROFIT, [A.REVENUE, A.COST_OF_SALES], year),
    ]
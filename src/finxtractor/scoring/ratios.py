from decimal import Decimal
from ..schemas.canonical import CanonicalStatement, CanonicalAccount as A
from .schemas import Ratio, MetricInput


def _input(stmt: CanonicalStatement, account: A, year: str = "current") -> MetricInput | None:
    line = stmt.get(account)
    if line is None:
        return None
    value = getattr(line, f"value_{year}")
    if value is None:
        return None
    prov = line.provenance
    return MetricInput(
        account=account.value, value=value,
        page=prov.page if prov else None,
        bbox=prov.bbox if prov else None,
    )

def _ratio(name: str, formula: str, numerator: MetricInput | None,
           denominator: MetricInput | None, extra: list[MetricInput] = None) -> Ratio:
    inputs = [i for i in ([numerator, denominator] + (extra or [])) if i is not None]
    if numerator is None or denominator is None:
        return Ratio(name=name, formula=formula, inputs=inputs,
                     note="undefined: missing input")
    if denominator.value == 0:
        return Ratio(name=name, formula=formula, inputs=inputs,
                     note="undefined: zero denominator")
    return Ratio(name=name, value=numerator.value / denominator.value,
                 formula=formula, inputs=inputs)

def net_profit_margin(stmt, year="current") -> Ratio:
    return _ratio("net_profit_margin", "net_profit / revenue",
                  _input(stmt, A.NET_PROFIT, year), _input(stmt, A.REVENUE, year))


def return_on_assets(stmt, year="current") -> Ratio:
    return _ratio("return_on_assets", "net_profit / total_assets",
                  _input(stmt, A.NET_PROFIT, year), _input(stmt, A.TOTAL_ASSETS, year))


def current_ratio(stmt, year="current") -> Ratio:
    return _ratio("current_ratio", "current_assets / current_liabilities",
                  _input(stmt, A.CURRENT_ASSETS, year), _input(stmt, A.CURRENT_LIABILITIES, year))


def debt_to_equity(stmt, year="current") -> Ratio:
    return _ratio("debt_to_equity", "total_liabilities / total_equity",
                  _input(stmt, A.TOTAL_LIABILITIES, year), _input(stmt, A.TOTAL_EQUITY, year))


def interest_coverage(stmt, year="current") -> Ratio:
    return _ratio("interest_coverage", "ebit / interest_expense",
                  _input(stmt, A.EBIT, year), _input(stmt, A.INTEREST_EXPENSE, year))

def compute_ratios(stmt: CanonicalStatement, year: str = "current") -> list[Ratio]:
    return [
        net_profit_margin(stmt, year),
        return_on_assets(stmt, year),
        current_ratio(stmt, year),
        debt_to_equity(stmt, year),
        interest_coverage(stmt, year),
    ]
from decimal import Decimal
from ..schemas.canonical import CanonicalStatement, CanonicalAccount as A
from .schemas import AltmanResult, Zone, MetricInput
from .ratios import _input            # reuse the provenance-lifting builder

# Z'' (private / non-manufacturer): 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
_C1, _C2, _C3, _C4 = Decimal("6.56"), Decimal("3.26"), Decimal("6.72"), Decimal("1.05")

# Zone cutoffs for the four-variable Z'' model (configurable — see note).
_SAFE_ABOVE = Decimal("2.6")
_DISTRESS_BELOW = Decimal("1.1")

def _x1(stmt, year):  # working capital / total assets — TWO inputs
    ca = _input(stmt, A.CURRENT_ASSETS, year)
    cl = _input(stmt, A.CURRENT_LIABILITIES, year)
    ta = _input(stmt, A.TOTAL_ASSETS, year)
    if not (ca and cl and ta) or ta.value == 0:
        return None, [i for i in (ca, cl, ta) if i]
    return (ca.value - cl.value) / ta.value, [ca, cl, ta]


def _div(stmt, num_acct, den_acct, year):
    num = _input(stmt, num_acct, year)
    den = _input(stmt, den_acct, year)
    if not (num and den) or den.value == 0:
        return None, [i for i in (num, den) if i]
    return num.value / den.value, [num, den]

def _zone(z: Decimal) -> Zone:
    if z > _SAFE_ABOVE:
        return Zone.SAFE
    if z < _DISTRESS_BELOW:
        return Zone.DISTRESS
    return Zone.GREY


def compute_altman(stmt: CanonicalStatement, year: str = "current") -> AltmanResult:
    x1, in1 = _x1(stmt, year)
    x2, in2 = _div(stmt, A.RETAINED_EARNINGS, A.TOTAL_ASSETS, year)
    x3, in3 = _div(stmt, A.EBIT, A.TOTAL_ASSETS, year)
    x4, in4 = _div(stmt, A.TOTAL_EQUITY, A.TOTAL_LIABILITIES, year)
    inputs = in1 + in2 + in3 + in4

    if None in (x1, x2, x3, x4):
        return AltmanResult(x1=x1, x2=x2, x3=x3, x4=x4, inputs=inputs)  # incomplete -> no score

    z = _C1 * x1 + _C2 * x2 + _C3 * x3 + _C4 * x4
    return AltmanResult(x1=x1, x2=x2, x3=x3, x4=x4,
                        z_double_prime=z, zone=_zone(z), inputs=inputs)
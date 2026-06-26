from decimal import Decimal
from .schemas import Ratio, AltmanResult, CompositeScore, Zone

# Each metric -> (good_at, bad_at): the value scoring 1.0 and the value scoring 0.0.
# Linear in between, clamped to [0,1]. Documented, tunable — not magic numbers.
_BANDS = {
    "net_profit_margin": (Decimal("0.20"), Decimal("0.00")),   # 20%+ excellent, 0% poor
    "return_on_assets":  (Decimal("0.10"), Decimal("0.00")),   # 10%+ excellent
    "current_ratio":     (Decimal("2.0"),  Decimal("1.0")),    # 2+ healthy, 1 marginal
    "debt_to_equity":    (Decimal("0.5"),  Decimal("2.5")),    # lower better (inverted)
    "interest_coverage": (Decimal("6.0"),  Decimal("1.0")),    # 6x+ strong, 1x fragile
}

# Weights — must sum to 1.0. Z'' carries the most because it's the holistic predictor.
_WEIGHTS = {
    "altman_zscore":     Decimal("0.30"),
    "interest_coverage": Decimal("0.18"),
    "debt_to_equity":    Decimal("0.17"),
    "current_ratio":     Decimal("0.15"),
    "return_on_assets":  Decimal("0.10"),
    "net_profit_margin": Decimal("0.10"),
}

def _sub_score(value: Decimal, good_at: Decimal, bad_at: Decimal) -> Decimal:
    if good_at == bad_at:
        return Decimal("0.5")
    raw = (value - bad_at) / (good_at - bad_at)      # 0 at bad_at, 1 at good_at
    return max(Decimal("0"), min(Decimal("1"), raw)) # clamp to [0,1]

def _altman_sub_score(altman: AltmanResult) -> Decimal | None:
    if altman is None or altman.z_double_prime is None:
        return None
    # Map the continuous Z'' onto 0-1 using the zone cutoffs as anchors.
    return _sub_score(altman.z_double_prime, Decimal("2.6"), Decimal("1.1"))

_GRADES = [   # (min score inclusive, letter) — the documented threshold table
    (Decimal("85"), "A"), (Decimal("70"), "B"), (Decimal("55"), "C"),
    (Decimal("40"), "D"), (Decimal("0"), "F"),
]


def _grade(score: Decimal) -> str:
    return next(letter for cutoff, letter in _GRADES if score >= cutoff)


def compute_composite(ratios: list[Ratio], altman: AltmanResult) -> CompositeScore:
    subs: dict[str, Decimal] = {}
    notes: list[str] = []

    for r in ratios:
        if r.value is None or r.name not in _BANDS:
            notes.append(f"{r.name}: excluded ({r.note or 'no band'})")
            continue
        good, bad = _BANDS[r.name]
        subs[r.name] = _sub_score(r.value, good, bad)

    a_sub = _altman_sub_score(altman)
    if a_sub is not None:
        subs["altman_zscore"] = a_sub
    else:
        notes.append("altman_zscore: excluded (incomplete)")

    # Reweight over only the metrics we actually have, so missing ones don't zero the score.
    active = {k: _WEIGHTS[k] for k in subs}
    total_w = sum(active.values()) or Decimal("1")
    blended = sum(subs[k] * (active[k] / total_w) for k in subs)

    score = Decimal(blended * 100).quantize(Decimal("0.1"))
    return CompositeScore(score_0_100=score, grade=_grade(score),
                          components={k: Decimal(v).quantize(Decimal("0.001")) for k, v in subs.items()},
                          notes=notes)
import re
from dataclasses import dataclass

from rapidfuzz import process, fuzz

from ..schemas.canonical import CanonicalAccount
from .aliases import ALIASES


@dataclass
class MatchResult:
    account: CanonicalAccount | None
    method: str          # "alias" | "fuzzy" | "unmapped"
    score: float


_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm(label: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — so both sides of a
    match compare on the same shape."""
    s = _PUNCT.sub(" ", label.lower())
    return _WS.sub(" ", s).strip()


# Normalized alias string -> canonical account (single source of truth: aliases.ALIASES).
_LABEL_TO_ACCOUNT: dict[str, CanonicalAccount] = {
    _norm(alias): account
    for account, aliases in ALIASES.items()
    for alias in aliases
}
_ALL_LABELS = list(_LABEL_TO_ACCOUNT.keys())


def match_exact(label: str) -> CanonicalAccount | None:
    return _LABEL_TO_ACCOUNT.get(_norm(label))


def match_fuzzy(label: str, threshold: int = 88) -> tuple[CanonicalAccount | None, float]:
    hit = process.extractOne(_norm(label), _ALL_LABELS, scorer=fuzz.token_sort_ratio)
    if hit and hit[1] >= threshold:
        return _LABEL_TO_ACCOUNT[hit[0]], hit[1]
    return None, hit[1] if hit else 0.0


def map_label(label: str) -> MatchResult:
    account = match_exact(label)
    if account is not None:
        return MatchResult(account, "alias", 100.0)
    account, score = match_fuzzy(label)
    if account is not None:
        return MatchResult(account, "fuzzy", score)
    return MatchResult(None, "unmapped", score)

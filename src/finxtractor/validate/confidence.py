from ..schemas.canonical import CanonicalStatement
from .results import CheckResult, CheckStatus, ValueConfidence

# How much we trust a value before any checks, by how it was produced.
_BASE = {
    "tableformer": 0.80,    # deterministic, structure-aware
    "vlm": 0.65,            # vision fallback — less certain
    "llm_mapped": 0.70,     # value extracted fine; only the label was LLM-mapped
}
_DEFAULT_BASE = 0.60


def _base_score(source: str) -> float:
    return _BASE.get(source, _DEFAULT_BASE)

def _source_for(line) -> str:
    if line.mapped_by == "llm":
        return "llm_mapped"
    # extraction route was recorded on provenance during parsing
    return "tableformer"        # VLM fork is dormant (Phase 2), so all real values are TableformerR

def _check_adjustment(account: str, checks: list[CheckResult]) -> tuple[float, int, int, list[str]]:
    delta, passed, failed, reasons = 0.0, 0, 0, []
    for c in checks:
        if account not in c.accounts:
            continue
        if c.status == CheckStatus.PASS:
            delta += 0.10
            passed += 1
            reasons.append(f"passed {c.name}")
        elif c.status == CheckStatus.FAIL:
            delta -= 0.40
            failed += 1
            reasons.append(f"FAILED {c.name}: {c.message}")
    return delta, passed, failed, reasons

def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_value(account: str, year: str, line, checks: list[CheckResult]) -> ValueConfidence:
    source = _source_for(line)
    base = _base_score(source)
    delta, passed, failed, reasons = _check_adjustment(account, checks)
    return ValueConfidence(
        account=account, year=year, score=_clamp(base + delta),
        extraction_source=source, checks_passed=passed, checks_failed=failed,
        reasons=reasons or [f"base {source} {base:.2f}, no checks touched this value"],
    )

def score_statement(stmt: CanonicalStatement, checks: list[CheckResult],
                    year: str = "current") -> list[ValueConfidence]:
    out = []
    for key, line in stmt.lines.items():
        if getattr(line, f"value_{year}") is None:
            continue
        out.append(score_value(key, year, line, checks))
    return out
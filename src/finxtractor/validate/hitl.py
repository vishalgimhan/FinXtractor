from .results import ValueConfidence, ValidationReport, CheckResult

REVIEW_THRESHOLD = 0.60      # below this, a human looks before the number is trusted


def apply_gate(confidences: list[ValueConfidence],
               threshold: float = REVIEW_THRESHOLD) -> list[ValueConfidence]:
    for vc in confidences:
        if vc.score < threshold:
            vc.flagged_for_review = True
            vc.reasons.append(f"below review threshold ({vc.score:.2f} < {threshold:.2f})")
    return confidences

def build_report(checks: list[CheckResult], confidences: list[ValueConfidence],
                 retries: int) -> ValidationReport:
    gated = apply_gate(confidences)
    return ValidationReport(
        checks=checks,
        confidences=gated,
        retries=retries,
        flagged_count=sum(1 for vc in gated if vc.flagged_for_review),
    )
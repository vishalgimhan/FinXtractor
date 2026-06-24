from pydantic import BaseModel
from ..schemas.canonical import CanonicalAccount
from ..llm.client import get_chat_model

_ACCOUNTS = [a.value for a in CanonicalAccount]


class LabelDecision(BaseModel):
    account: str | None      # a canonical account value, or None if no good fit
    reasoning: str


def map_label_llm(label: str) -> tuple[CanonicalAccount | None, str]:
    model = get_chat_model().with_structured_output(LabelDecision)
    prompt = (
        "You map a financial-statement line label to ONE canonical account, "
        "or null if none fits. Choose ONLY from this exact list:\n"
        f"{_ACCOUNTS}\n\n"
        f"Label: {label!r}\n"
        "Return the canonical account string exactly as listed, or null."
    )
    decision = model.invoke(prompt)
    if decision.account in _ACCOUNTS:
        return CanonicalAccount(decision.account), decision.reasoning
    return None, decision.reasoning      # null or hallucinated value -> unmapped
from pydantic import BaseModel
from ..schemas.canonical import CanonicalAccount
from ..llm.client import get_chat_model
from ..llm.prompts import label_mapping_prompt

_ACCOUNTS = [a.value for a in CanonicalAccount]


class LabelDecision(BaseModel):
    account: str | None      # a canonical account value, or None if no good fit
    reasoning: str


def map_label_llm(label: str) -> tuple[CanonicalAccount | None, str]:
    model = get_chat_model().with_structured_output(LabelDecision)
    decision = model.invoke(label_mapping_prompt(_ACCOUNTS, label))
    if decision.account in _ACCOUNTS:
        return CanonicalAccount(decision.account), decision.reasoning
    return None, decision.reasoning      # null or hallucinated value -> unmapped
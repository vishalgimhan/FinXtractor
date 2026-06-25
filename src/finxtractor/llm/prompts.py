"""LLM prompt templates, kept separate from the call sites that use them."""


def label_mapping_prompt(accounts: list[str], label: str) -> str:
    """Prompt for mapping a raw statement label to one canonical account (or null)."""
    return (
        "You map a financial-statement line label to ONE canonical account, "
        "or null if none fits. Choose ONLY from this exact list:\n"
        f"{accounts}\n\n"
        "Be conservative: map ONLY a primary total/standard statement line "
        "(e.g. a revenue total, profit/loss subtotal, total assets/liabilities/"
        "equity). Return null for a breakdown or component line (e.g. 'Advisory "
        "fees', 'Net trading income', 'Deferred tax assets') — these are NOT the "
        "canonical totals. When unsure, return null.\n\n"
        f"Label: {label!r}\n"
        "Return the canonical account string exactly as listed, or null."
    )

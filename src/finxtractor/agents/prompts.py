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


def statement_extraction_prompt() -> str:
    """Prompt for the VLM fallback: read a rasterized financial-statement page
    image and return its rows + metadata as structured data."""
    return (
        "You are reading one page of a financial report, rendered as an image. "
        "It contains a financial statement table (e.g. income statement / "
        "statement of profit or loss, or a balance sheet / statement of financial "
        "position).\n\n"
        "Extract EVERY line item row exactly as printed. For each row return:\n"
        "- label: the row label, verbatim\n"
        "- value_current: the most-recent-year figure as a number "
        "(negatives as negative numbers; a dash/blank means null)\n"
        "- value_prior: the comparative (older) year figure, same rules\n"
        "- note_ref: the note/reference number if the row cites one (e.g. '4', "
        "'3(a)'), else null\n"
        "- is_subtotal: true for total/subtotal rows (labels containing 'total', "
        "or net profit/loss, profit/loss before/after tax, total comprehensive)\n\n"
        "Also return the statement metadata:\n"
        "- year_current / year_prior: the two reporting years (integers) from the "
        "column headers\n"
        "- currency: ISO code if shown (e.g. 'AUD', 'USD'), else null\n"
        "- units: one of 'actual', 'thousands', 'millions' based on any "
        "'$'000' / 'in millions' note, else 'actual'\n\n"
        "Do not invent rows. Preserve sign. Numbers only in the value fields "
        "(strip currency symbols, commas, and parentheses — but keep the sign)."
    )


def toc_extraction_prompt(toc_text: str) -> str:
    """Prompt for structuring a printed 'Contents' page into title/page entries."""
    return (
        "Below is the raw text of a financial report's table-of-contents "
        "('Contents') page. Convert it into structured entries.\n\n"
        "For EACH listed item return:\n"
        "- title: the section/statement title, verbatim\n"
        "- page: the printed page number listed against it (an integer)\n\n"
        "Include every line that has a page number (primary statements, notes, "
        "directors' report, etc.). Skip group headers that carry no page number. "
        "Do not invent entries or page numbers.\n\n"
        "Contents page text:\n"
        f"{toc_text}"
    )

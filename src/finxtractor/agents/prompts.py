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


def resolver_system_prompt() -> str:
    """System prompt for the page-resolver agent: an LLM that drives the
    statement-page-location tiers via tools and decides when to stop."""
    return (
        "You locate the financial-statement pages in a PDF annual report: the "
        "INCOME statement (statement of profit or loss) and the BALANCE sheet "
        "(statement of financial position). You work through TOOLS — you never "
        "read the page text yourself; each tool returns a compact result.\n\n"
        "Recommended workflow (escalate only as needed, cheapest tier first):\n"
        "1. extract_pages_tool — always first; loads the pages.\n"
        "2. assess_text_layer_tool — classify the PDF ('ok'/'sparse'/'none').\n"
        "3. build_page_index_tool, then lookup_page_index for each kind — the "
        "unified agentic-TOC + outline index, the most reliable source.\n"
        "4. For any kind still missing on a TEXT pdf (text_layer != 'none'): "
        "lookup_printed_toc_and_heuristic.\n"
        "5. For any kind still missing, or whenever text_layer == 'none' "
        "(scanned): scan_pdf — this is expensive (OCR + VLM), so use it last.\n\n"
        "Rules:\n"
        "- Stop as soon as both kinds are found, or every applicable tier has "
        "missed. Do not call a tool twice for the same kind once it is found.\n"
        "- On a scanned PDF (text_layer == 'none') the printed-TOC/heuristic "
        "tier is useless — skip it and go straight to scan_pdf.\n"
        "- The income statement is the priority; the balance sheet may be "
        "absent. Never invent a page number — only report pages a tool returned.\n"
        "- When done, return the structured result: the located page and the "
        "source tier for each kind, or null if it could not be located."
    )


def resolver_user_prompt(pdf_name: str, income_override: int | None,
                         bs_override: int | None) -> str:
    """Per-run request for the page-resolver agent."""
    lines = [
        f"Locate the income statement and balance sheet pages in '{pdf_name}'.",
    ]
    if income_override is not None:
        lines.append(f"The income statement page is already known: {income_override}. "
                     "Use it as-is (source 'override'); do not search for it.")
    if bs_override is not None:
        lines.append(f"The balance sheet page is already known: {bs_override}. "
                     "Use it as-is (source 'override'); do not search for it.")
    lines.append("Begin with extract_pages_tool.")
    return "\n".join(lines)


def page_classification_prompt(kinds: list[str]) -> str:
    """Prompt for the VLM page classifier: which statement (if any) a page image is."""
    return (
        "You are shown ONE page of a financial report as an image. Decide which "
        f"of these financial statements it primarily is: {kinds}.\n"
        "- If the page IS one of them (the actual statement table), return that "
        "exact kind string.\n"
        "- If it is none of them (narrative text, notes, a contents/index page, "
        "an auditor's report, etc.), return null.\n"
        "Return only the kind or null."
    )

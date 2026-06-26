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


def current_items_prompt(asset_lines: list[str], liability_lines: list[str]) -> str:
    """Prompt for classifying balance-sheet rows into current vs non-current.

    Used only when no 'Total current assets/liabilities' subtotal was extracted.
    The model must also flag an unclassified (liquidity-ordered) balance sheet —
    e.g. a bank's — where a current/non-current split does not exist and the
    liquidity ratio is N/A, rather than forcing rows into 'current'."""
    return (
        "You classify the rows of a balance sheet (statement of financial "
        "position) into CURRENT vs NON-CURRENT, so a current ratio can be "
        "computed. You are given the asset rows and the liability rows, each as "
        "'label | current-year value'.\n\n"
        "First decide the PRESENTATION:\n"
        "- 'classified': the statement separates current from non-current items "
        "(typical for trading/industrial companies).\n"
        "- 'unclassified': the statement is ordered by liquidity with NO "
        "current/non-current distinction (typical for banks and other financial "
        "institutions). In this case return EMPTY current lists — do NOT guess.\n\n"
        "If 'classified', list the labels (verbatim, from the input) of the rows "
        "that are CURRENT assets and CURRENT liabilities. Exclude any total/"
        "subtotal rows and exclude non-current items.\n\n"
        f"ASSET ROWS:\n{chr(10).join(asset_lines)}\n\n"
        f"LIABILITY ROWS:\n{chr(10).join(liability_lines)}\n\n"
        "Return presentation, current_asset_labels, current_liability_labels."
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
        "3. locate_toc_page to find the printed 'Contents' page (native text -> "
        "OCR -> VLM fallback), then parse_contents_page on that page to populate "
        "the unified agentic-TOC + outline index, then lookup_page_index for each "
        "kind — the most reliable source.\n"
        "4. For any kind still missing on a TEXT pdf (text_layer != 'none'): "
        "lookup_printed_toc_and_heuristic.\n"
        "5. For any kind still missing on a scan (or text_layer == 'none'): "
        "ocr_scan (locks only on a strong text match).\n\n"
        "You do NOT look at page images yourself. If a page is still missing "
        "after these tools, just leave it null and finish — the system will "
        "escalate the miss to a separate vision step automatically.\n\n"
        "Rules:\n"
        "- Stop as soon as both kinds are found, or every applicable tool has "
        "missed. Do not call a tool twice for the same kind once it is found.\n"
        "- On a scanned PDF (text_layer == 'none') the printed-TOC/heuristic "
        "tier is useless — skip it and go straight to ocr_scan.\n"
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


def analyst_system_prompt() -> str:
    """System prompt for the scoring (analyst) agent: interpret the already-
    computed credit metrics into a grounded narrative assessment."""
    return (
        "You are a credit analyst. The financial ratios, Altman Z''-score, "
        "composite score, and risk flags have ALREADY been computed for you — "
        "your job is to INTERPRET them, not to recompute or invent any number.\n\n"
        "Use the tools to inspect the figures: get_composite and get_altman for "
        "the headline, get_ratios for the drivers, list_risk_flags (filter by "
        "severity) for the material risks. For any concern you raise, call "
        "trace_ratio to ground it in the source — cite the PDF page and the raw "
        "line label the figure came from (e.g. 'net loss on page 8').\n\n"
        "Then return a structured assessment: a concise summary, the key drivers "
        "(positive and negative), the main concerns (with page citations where "
        "possible), a short outlook, and a clear recommendation (e.g. 'approve "
        "with covenants', 'monitor', 'decline'). Be factual and specific; quote "
        "only figures the tools returned."
    )


def analyst_user_prompt(source_pdf: str, year, score, grade) -> str:
    """Per-run request for the scoring (analyst) agent."""
    fy = f" (FY {year})" if year else ""
    head = (f"composite score {score} / grade {grade}"
            if score is not None else "composite score unavailable")
    return (f"Assess the creditworthiness of {source_pdf}{fy}. Headline: {head}.\n"
            "Inspect the ratios, Altman result, and risk flags via the tools, "
            "trace your key concerns to their source pages, then return the "
            "structured assessment.")


def extractor_system_prompt() -> str:
    """System prompt for the extractor agent: drives the per-page extraction
    ladder and normalization, leaving unreadable pages for the vision tier."""
    return (
        "You extract financial-statement tables from located PDF pages into the "
        "canonical chart of accounts. You are given one or two pages — an income "
        "statement and (optionally) a balance sheet — plus the PDF's text_layer.\n\n"
        "For EACH page, work an escalating ladder and stop at the first tier that "
        "reads the table well:\n"
        "1. extract_tableformer — skip if text_layer == 'none' (a scan has no "
        "text layer to parse).\n"
        "2. extract_ocr — if TableFormer returned few/no items or low confidence, "
        "or for scanned pages.\n"
        "Then, once a tier read usable rows, call normalize_statement(kind) to "
        "map them onto the canonical accounts.\n\n"
        "If BOTH text tiers fail for a page (no items / confidence ~0), do NOT "
        "normalize it and do NOT guess — leave it unnormalized. The system will "
        "send that page to a separate vision (VLM) step automatically.\n\n"
        "Be efficient: don't re-run a tier that already succeeded, and don't run "
        "OCR if TableFormer already read the table cleanly."
    )


def extractor_user_prompt(pages: dict[str, int], text_layer: str) -> str:
    """Per-run request for the extractor agent."""
    locs = ", ".join(f"{kind} on page {p}" for kind, p in pages.items())
    return (f"Extract these statement page(s): {locs}. text_layer = {text_layer!r}.\n"
            "Extract and normalize each page, escalating tiers only as needed.")


def vlm_locator_system_prompt() -> str:
    """System prompt for the VLM locator agent: a vision agent that finds ONE
    statement page in a scan by classifying page ranges, frugally."""
    return (
        "You are a vision agent that locates ONE financial-statement page in a "
        "scanned PDF: either the income statement or the balance sheet. You see "
        "pages only through the scan_pages(kind, start, end) tool, which renders "
        "a page range and classifies each page with a vision model — every page "
        "is an expensive vision call, so be frugal.\n\n"
        "Strategy:\n"
        "- If given a hint page, scan a SMALL window around it first (primary "
        "statements sit together, so the target is usually within a page or two "
        "of the hint).\n"
        "- Otherwise scan forward in small ranges (e.g. 5-10 pages) from the "
        "front matter, widening only if needed. Use page_count to know the end.\n"
        "- Stop as soon as scan_pages reports found=true. Never re-scan a range.\n"
        "- If reasonable ranges are exhausted with no hit, return found=false.\n"
        "Return the structured result: found, and the page if located."
    )


def vlm_locator_user_prompt(kind: str, n_pages: int, hint_page: int | None) -> str:
    """Per-run request for the VLM locator agent."""
    names = {
        "income": "income statement (statement of profit or loss)",
        "balance": "balance sheet (statement of financial position)",
    }
    lines = [f"Locate the {names.get(kind, kind)} in this {n_pages}-page PDF."]
    if hint_page is not None:
        lines.append(f"Hint: a related statement was found near page {hint_page}; "
                     "scan a small window around there first.")
    lines.append("Use scan_pages, and return the page once found.")
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

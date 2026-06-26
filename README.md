# FinXtractor

**Agentic extraction and credit scoring of Australian annual-report PDFs.**

FinXtractor reads a company's annual report, locates the income statement and
balance sheet, extracts them into a typed **canonical chart of accounts** (with
note links, financial-year alignment, and currency/rounding detection),
validates them (cross-foot checks, confidence scoring, a human-in-the-loop
gate), and computes a **credit scorecard** — financial ratios, an Altman Z''
solvency score, and a composite credit grade with a structured risk report.

The whole flow is orchestrated as a **LangGraph** state machine. Python 3.11+,
managed with **Poetry**, packaged as `finxtractor` with a Typer CLI, a FastAPI
streaming service, and a Streamlit dashboard.

---

## Pipeline

```
resolver → extractor → validator ─→ retry → (back to extractor)
   │ (unresolved)         │        ─→ hitl   (terminal)
   └──────→ hitl          └─────────→ scoring (terminal, clean route)
```

- **resolver** — locate the statement pages (explicit override → unified
  agentic-TOC + embedded-outline page index → printed-TOC/heuristic → scanned
  OCR+VLM locator). Also assesses the text layer (`ok` / `sparse` / `none`).
- **extractor** — an escalating ladder: Docling TableFormer (text) →
  TableFormer + OCR → VLM. The best tier above the confidence floor wins; then
  normalize to the canonical chart and merge income + balance.
- **validator** — cross-foot checks, per-value confidence scoring, HITL gate.
- **retry** — re-extract (pages already resolved) up to `max_retries`.
- **hitl** — terminal; surfaces flagged values or a resolution failure.
- **scoring** — ratios, Altman Z'', composite credit score, risk flags →
  `CreditReport`.

`validate` / `pipeline` exit non-zero when values are flagged for human review.

---

## Setup

```bash
poetry install            # or: make setup
```

Secrets/config live in `.env` (gitignored) — copy `.env.example` to start.

The LLM/VLM tiers can run either against **OpenRouter** (default in
`config/models.yaml`) or fully offline against **Ollama** in Docker:

```bash
docker compose up -d                                    # starts finxtractor-ollama on :11434
docker exec finxtractor-ollama ollama pull qwen3:8b     # chat model
docker exec finxtractor-ollama ollama pull qwen3-vl:8b  # vision model (VLM fallback)
```

Switch provider per run without editing files:

```bash
FINX_LLM_PROVIDER=ollama poetry run finxtractor pipeline data/reports/<pdf_name>.pdf
```

Backend selection is overridable via env: `FINX_LLM_PROVIDER`,
`FINX_VLM_PROVIDER`, `FINX_TABLE_BACKEND`, `FINX_PDF_READER`.

---

## CLI

All commands take a PDF path; pages auto-resolve unless `--page` / `--*-page` is given.

```bash
poetry run finxtractor run        <pdf>                       # page-count wiring check
poetry run finxtractor extract    <pdf> [--page N]            # raw table extraction
poetry run finxtractor canonical  <pdf> [--page N] [--use-llm]
poetry run finxtractor canonical-full <pdf> --income-page N --bs-page M
poetry run finxtractor validate   <pdf> --income-page N --bs-page M
poetry run finxtractor pipeline   <pdf>                       # full LangGraph pipeline (preferred)
poetry run finxtractor breakdown  <pdf> "Revenue"             # drill into a line item's children
poetry run finxtractor note-refs  <pdf> 5                     # line items referencing note 5
```

---

## Dashboard & API

```bash
make dashboard     # Streamlit analyst UI (src/finxtractor/dashboard.py)
make api           # FastAPI streaming service (api/main.py) on :8000
make start         # both together
```

The dashboard renders the credit grade, ratios (with input **provenance** —
reported / derived / agent-classified / N/A), the Altman Z'' breakdown, risk
flags, the full ledger, and an opt-in note-linking knowledge graph that traces
each line item to its source note tables.

---

## Configuration

- `config/models.yaml` — model providers/names (chat LLM, VLM, table extractor, PDF reader).
- `config/param.yaml` — tunables (triage thresholds, fuzzy cutoff, retries, tolerances, confidence bases).
- `config/patterns.yaml` — statement markers and regexes.

Thresholds, model names, and markers are not hard-coded — they route through `config.py`.

---

## Tests

```bash
poetry run pytest
```

---

## Tech stack

| Concern | Choice |
|---|---|
| Agentic orchestration | LangGraph + LangChain (tool-driven agents) |
| Schemas / validation | Pydantic |
| Table extraction (DLA) | Docling TableFormer (+ RapidOCR ONNX fallback) |
| PDF reading / rasterization | PyMuPDF |
| Vision fallback | Qwen-3 VL (Ollama / OpenRouter) |
| Knowledge graph | NetworkX |
| CLI / API / UI | Typer · FastAPI · Streamlit |
| Packaging | Poetry |

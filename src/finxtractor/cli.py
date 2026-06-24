from pathlib import Path
import json

import typer
import fitz
from loguru import logger

from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import resolve_income_page
from finxtractor.parsing.vlm_fallback import extract_income_statement
from finxtractor.parsing.notes import resolve_line_item_notes
from finxtractor.graph.builder import build_graph
from finxtractor.graph.queries import drill_down, referencing_line_items
from finxtractor.normalize.normalize import normalize, pull_balance_sheet, merge
from finxtractor.normalize.normalize import normalize
from finxtractor.normalize.balance_sheet import pull_balance_sheet, merge
from finxtractor.validate.retry import validate_with_retry
from finxtractor.validate.checks import run_all_checks
from finxtractor.validate.confidence import score_statement
from finxtractor.validate.hitl import build_report

app = typer.Typer()

def _resolved_page(pdf: Path) -> int:
    page, _source = resolve_income_page(pdf, extract_pages(pdf))
    if page is None:
        raise typer.BadParameter("No income page found; pass --page")
    return page


def _build_statement(pdf: Path, page: int):
    stmt = extract_income_statement(pdf, page)
    resolve_line_item_notes(stmt)
    return stmt

@app.command()
def run(pdf: Path):
    """Load a PDF and print its page count (wiring check)."""
    if not pdf.exists():
        raise typer.BadParameter(f"No file at {pdf}")
    doc = fitz.open(pdf)
    typer.echo(f"{pdf.name}: {doc.page_count} pages")
    doc.close()

@app.command()
def extract(
    pdf: Path,
    page: int | None = typer.Option(None, "--page", help="1-based page number of the income statement (auto-detected if omitted)")
    ):
    """Parse one report's income statement into typed rows with provenance (JSON)."""
    if not pdf.exists():
        raise typer.BadParameter(f"No file at {pdf}")
    logger.info("Starting extract for {}", pdf.name)
    if page is None:
        page, source = resolve_income_page(pdf, extract_pages(pdf))
        if page is None:
            raise typer.BadParameter("No income-statement page found; try --page")
        typer.echo(f"Auto-selected page {page} (via {source}) as income-statement page", err=True)
        logger.info("Auto-selected page {} via {}", page, source)
    else:
        logger.info("Using explicit page {}", page)
    stmt = _build_statement(pdf, page)
    logger.debug("Finished extract for {} with {} line item(s)", pdf.name, len(stmt.line_items))
    typer.echo(stmt.model_dump_json(indent=2))

@app.command()
def breakdown(pdf: Path, label: str, page: int = typer.Option(None, "--page")):
    """Show the full breakdown behind a line item (e.g. 'Revenue')."""
    page = page or _resolved_page(pdf)
    stmt = _build_statement(pdf, page)
    G = build_graph(stmt, pdf)
    typer.echo(json.dumps(drill_down(G, label), indent=2, default=str))


@app.command("note-refs")
def note_refs(pdf: Path, number: int, page: int = typer.Option(None, "--page")):
    """Show which line items reference a given note number."""
    page = page or _resolved_page(pdf)
    stmt = _build_statement(pdf, page)
    G = build_graph(stmt, pdf)
    typer.echo(json.dumps(referencing_line_items(G, number), indent=2, default=str))

@app.command()
def canonical(
    pdf: Path,
    page: int = typer.Option(None, "--page"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Enable the LLM mapping tier for unmatched subtotal lines"),
):
    """Extract, map, and normalize one report's income statement to canonical form."""
    page = page or _resolved_page(pdf)
    stmt = _build_statement(pdf, page)
    cs = normalize(stmt, use_llm=use_llm)
    typer.echo(cs.model_dump_json(indent=2))

@app.command("canonical-full")
def canonical_full(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Enable the LLM mapping tier for unmatched subtotal lines"),
):
    """Full canonical pull: income statement + targeted balance-sheet items."""
    ip = income_page or _resolved_page(pdf)
    income = normalize(_build_statement(pdf, ip), use_llm=use_llm)
    balance = pull_balance_sheet(pdf, bs_page, use_llm=use_llm)
    full = merge(income, balance)
    typer.echo(full.model_dump_json(indent=2))

@app.command()
def validate(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
):
    """Full pipeline: extract -> normalize -> cross-foot -> retry -> confidence -> HITL gate."""
    ip = income_page or _resolved_page(pdf)
    income = normalize(_build_statement(pdf, ip))
    full = merge(income, pull_balance_sheet(pdf, bs_page))

    stmt, checks, retries = validate_with_retry(pdf, full, ip, bs_page)
    confidences = score_statement(stmt, checks)
    report = build_report(checks, confidences, retries)

    typer.echo(report.model_dump_json(indent=2))
    if report.flagged_count:
        typer.echo(f"\n⚠ {report.flagged_count} value(s) flagged for review", err=True)
        raise typer.Exit(code=1)            # non-zero exit = "needs a human"
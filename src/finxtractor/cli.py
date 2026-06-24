from pathlib import Path
import json

import typer
import fitz
from loguru import logger

from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import resolve_income_page
# from finxtractor.parsing.parser import parse_income_statement
from finxtractor.parsing.docling_parser import parse_income_statement
from finxtractor.parsing.vlm_fallback import extract_income_statement
from finxtractor.parsing.notes import resolve_line_item_notes
from finxtractor.graph.builder import build_graph
from finxtractor.graph.queries import drill_down, referencing_line_items

app = typer.Typer()

def _resolved_page(pdf: Path) -> int:
    from finxtractor.parsing.text import extract_pages
    from finxtractor.parsing.routing import rank_income_pages
    ranked = rank_income_pages(extract_pages(pdf))
    if not ranked:
        raise typer.BadParameter("No income page found; pass --page")
    return ranked[0]


def _build_statement(pdf: Path, page: int):
    from finxtractor.parsing.vlm_fallback import extract_income_statement
    from finxtractor.parsing.notes import resolve_line_item_notes
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
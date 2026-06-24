from pathlib import Path
import typer
import fitz
from loguru import logger

from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import resolve_income_page
# from finxtractor.parsing.parser import parse_income_statement
from finxtractor.parsing.docling_parser import parse_income_statement
from finxtractor.parsing.vlm_fallback import extract_income_statement
from finxtractor.parsing.notes import resolve_line_item_notes

app = typer.Typer()

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
    stmt = extract_income_statement(pdf, page)
    resolve_line_item_notes(stmt)
    logger.debug("Finished extract for {} with {} line item(s)", pdf.name, len(stmt.line_items))
    typer.echo(stmt.model_dump_json(indent=2))
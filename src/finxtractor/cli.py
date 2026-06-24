from pathlib import Path
import typer
import fitz

from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import rank_income_pages
# from finxtractor.parsing.parser import parse_income_statement
from finxtractor.parsing.docling_parser import parse_income_statement

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
    page: int = typer.Option(None, "--page", help="1-based page number of the income statement (auto-detected if omitted)")
    ):
    """Parse one report's income statement into typed rows with provenance (JSON)."""
    if not pdf.exists():
        raise typer.BadParameter(f"No file at {pdf}")
    if page is None:
        ranked = rank_income_pages(extract_pages(pdf))
        if not ranked:
            raise typer.BadParameter("No income-statement page found; try --page")
        page = ranked[0]
        typer.echo(f"Auto-selected page {page} as most likely income-statement page")
    stmt = parse_income_statement(pdf, page)
    typer.echo(stmt.model_dump_json(indent=2))
from pathlib import Path
import typer
import fitz

from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import rank_income_pages
from finxtractor.parsing.parser import parse_income_statement

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
def extract(pdf: Path):
    """Parse one report's income statement into typed rows (JSON)."""
    if not pdf.exists():
        raise typer.BadParameter(f"No file at {pdf}")
    pages = extract_pages(pdf)
    income = rank_income_pages(pages)
    if not income:
        raise typer.BadParameter("No income-statement page found")
    stmt = parse_income_statement(pages, income[0], pdf.name)
    typer.echo(stmt.model_dump_json(indent=2))
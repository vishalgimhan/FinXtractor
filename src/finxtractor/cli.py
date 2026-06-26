import sys
from pathlib import Path
import json
import uuid

import typer
from loguru import logger

# CLI emits UTF-8 (JSON may carry −, ⚠, accented names) even on cp1252 consoles.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from finxtractor.config import get_param
from finxtractor.services.pdf_reader import get_pdf_reader
from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import resolve_page, INCOME_MARKERS, BALANCE_SHEET_MARKERS
from finxtractor.parsing.statements import extract_statement, extract_canonical
from finxtractor.graph.builder import build_graph
from finxtractor.graph.queries import drill_down, referencing_line_items
from finxtractor.normalize.normalize import merge
from finxtractor.validate.retry import validate_with_retry
from finxtractor.validate.checks import run_all_checks
from finxtractor.validate.confidence import score_statement
from finxtractor.validate.hitl import build_report
from finxtractor.orchestration.graph import compiled_pipeline
from finxtractor.orchestration.orchestrator import orchestrate, DocSpec

app = typer.Typer()

def _resolved_page(pdf: Path, markers: list) -> int:
    page, _source = resolve_page(pdf, extract_pages(pdf), markers)
    if page is None:
        raise typer.BadParameter("No income page found; pass --page")
    return page


def _build_statement(pdf: Path, page: int):
    return extract_statement(pdf, page)   # raw Statement (parse + VLM gate + notes)

@app.command()
def run(pdf: Path):
    """Load a PDF and print its page count (wiring check)."""
    if not pdf.exists():
        raise typer.BadParameter(f"No file at {pdf}")
    logger.info("Opening {} for page-count check", pdf.name)
    count = get_pdf_reader().page_count(pdf)
    typer.echo(f"{pdf.name}: {count} pages")
    logger.debug("Page-count check complete for {}", pdf.name)

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
        page, source = resolve_page(pdf, extract_pages(pdf), INCOME_MARKERS)
        if page is None:
            raise typer.BadParameter("No income-statement page found; try --page")
        typer.echo(f"Auto-selected page {page} (via {source}) as income-statement page", err=True)
        logger.info("Auto-selected page {} via {}", page, source)
    else:
        logger.info("Using explicit page {}", page)
    stmt = _build_statement(pdf, page)
    logger.info("Built statement for {} page {} with {} line item(s)", pdf.name, page, len(stmt.line_items))
    logger.debug("Finished extract for {} with {} line item(s)", pdf.name, len(stmt.line_items))
    typer.echo(stmt.model_dump_json(indent=2))

@app.command()
def breakdown(pdf: Path, label: str, page: int = typer.Option(None, "--page")):
    """Show the full breakdown behind a line item (e.g. 'Revenue')."""
    page = page or _resolved_page(pdf, INCOME_MARKERS)
    logger.info("Running breakdown for {} label {!r} on page {}", pdf.name, label, page)
    stmt = _build_statement(pdf, page)
    G = build_graph(stmt, pdf)
    logger.debug("Built breakdown graph for {} label {!r}", pdf.name, label)
    typer.echo(json.dumps(drill_down(G, label), indent=2, default=str))


@app.command("note-refs")
def note_refs(pdf: Path, number: int, page: int = typer.Option(None, "--page")):
    """Show which line items reference a given note number."""
    page = page or _resolved_page(pdf, INCOME_MARKERS)
    logger.info("Running note-refs for {} note {} on page {}", pdf.name, number, page)
    stmt = _build_statement(pdf, page)
    G = build_graph(stmt, pdf)
    logger.debug("Built note-reference graph for {} note {}", pdf.name, number)
    typer.echo(json.dumps(referencing_line_items(G, number), indent=2, default=str))

@app.command()
def canonical(
    pdf: Path,
    page: int = typer.Option(None, "--page"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Enable the LLM mapping tier for unmatched subtotal lines"),
):
    """Extract, map, and normalize one report's income statement to canonical form."""
    page = page or _resolved_page(pdf, INCOME_MARKERS)
    logger.info("Running canonical extract for {} on page {} (llm={})", pdf.name, page, use_llm)
    cs = extract_canonical(pdf, page, use_llm=use_llm)
    logger.info("Canonical statement built for {} with {} canonical line(s)", pdf.name, len(cs.lines))
    typer.echo(cs.model_dump_json(indent=2))

@app.command("canonical-full")
def canonical_full(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
    use_llm: bool = typer.Option(False, "--use-llm", help="Enable the LLM mapping tier for unmatched subtotal lines"),
):
    """Full canonical pull: income statement + targeted balance-sheet items."""
    ip = income_page or _resolved_page(pdf, INCOME_MARKERS)
    bsp = bs_page or _resolved_page(pdf, BALANCE_SHEET_MARKERS)
    logger.info("Running canonical-full for {} (income_page={}, bs_page={}, llm={})", pdf.name, ip, bsp, use_llm)
    income = extract_canonical(pdf, ip, use_llm=use_llm)
    balance = extract_canonical(pdf, bsp, use_llm=use_llm)
    full = merge(income, balance)
    logger.info("Merged canonical statements for {} into {} line(s)", pdf.name, len(full.lines))
    typer.echo(full.model_dump_json(indent=2))

@app.command()
def validate(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
):
    """Full pipeline: extract -> normalize -> cross-foot -> retry -> confidence -> HITL gate."""
    ip = income_page or _resolved_page(pdf, INCOME_MARKERS)
    bsp = bs_page or _resolved_page(pdf, BALANCE_SHEET_MARKERS)
    logger.info("Running validate pipeline for {} (income_page={}, bs_page={})", pdf.name, ip, bsp)
    income = extract_canonical(pdf, ip)
    full = merge(income, extract_canonical(pdf, bsp))

    stmt, checks, retries = validate_with_retry(pdf, full, ip, bsp)
    confidences = score_statement(stmt, checks)
    report = build_report(checks, confidences, retries)
    logger.info("Validation finished for {} with {} check(s), {} retry(ies), {} flagged", pdf.name, len(checks), retries, report.flagged_count)

    typer.echo(report.model_dump_json(indent=2))
    if report.flagged_count:
        typer.echo(f"\n⚠ {report.flagged_count} value(s) flagged for review", err=True)
        raise typer.Exit(code=1)            # non-zero exit = "needs a human"

@app.command()
def pipeline(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
    max_retries: int = typer.Option(get_param("validation", "max_retries", default=2), "--max-retries"),
):
    """Run the full LangGraph pipeline for one report."""
    # Pages are resolved inside the graph (resolver node); pass overrides if given.
    logger.info("Running pipeline for {} (income_page={}, bs_page={}, max_retries={})", pdf.name, income_page, bs_page, max_retries)
    graph = compiled_pipeline()
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    initial = {"pdf": str(pdf), "income_page": income_page, "bs_page": bs_page,
               "retries": 0, "max_retries": max_retries}

    final = graph.invoke(initial, config)

    logger.info("Pipeline finished for {} with route={}, retries={}, flagged={}", pdf.name, final.get('route'), final.get('retries', 0), final['report'].flagged_count)
    typer.echo(f"income page : {final.get('income_page')} (via {final.get('income_page_source')})")
    typer.echo(f"bs page     : {final.get('bs_page')} (via {final.get('bs_page_source')})")
    typer.echo(f"route taken : {final.get('route')}")
    typer.echo(f"retries     : {final.get('retries', 0)}")
    typer.echo(f"flagged     : {final['report'].flagged_count}")
    typer.echo(final["report"].model_dump_json(indent=2))

    credit = final.get("credit_report")
    if credit is not None:
        typer.echo("\n--- credit report ---")
        typer.echo(credit.model_dump_json(indent=2))
    if final.get("route") == "hitl":
        raise typer.Exit(code=1)

@app.command("run-all")
def run_all(max_retries: int = typer.Option(2, "--max-retries")):
    """Run all four reports through the pipeline. Edit the specs to match your files."""
    specs = [
        DocSpec("data/reports/report1.pdf", income_page=__, bs_page=__),
        DocSpec("data/reports/report2.pdf", income_page=__, bs_page=__),
        DocSpec("data/reports/report3.pdf", income_page=__, bs_page=__),
        DocSpec("data/reports/report4.pdf", income_page=__, bs_page=__),
    ]
    logger.info("Running batch pipeline for {} document(s) with max_retries={}", len(specs), max_retries)
    results = orchestrate(specs, max_retries)
    typer.echo(f"\n{'REPORT':30} {'ROUTE':10} {'RETRIES':8} {'FLAGGED':8}")
    for r in results:
        typer.echo(f"{Path(r.pdf).name:30} {r.route:10} {r.retries:<8} {r.flagged:<8}"
                   + (f"  ⚠ {r.error}" if r.error else ""))
    if any(r.route in ("hitl", "error") for r in results):
        raise typer.Exit(code=1)
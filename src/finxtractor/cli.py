import sys
from pathlib import Path
import json

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
from finxtractor.parsing.docling_parser import parse_statement
from finxtractor.parsing.notes import resolve_line_item_notes
from finxtractor.graph.builder import build_graph
from finxtractor.graph.queries import drill_down, referencing_line_items
from finxtractor.orchestration.graph import compiled_pipeline
from finxtractor.orchestration.orchestrator import orchestrate, DocSpec

app = typer.Typer()

def _resolved_page(pdf: Path, markers: list) -> int:
    page, _source = resolve_page(pdf, extract_pages(pdf), markers)
    if page is None:
        raise typer.BadParameter("No income page found; pass --page")
    return page


def _build_statement(pdf: Path, page: int):
    """Raw single-page Statement (TableFormer parse + resolved note refs) — the
    fast, non-agentic inspection primitive behind the debug commands."""
    stmt = parse_statement(pdf, page)
    resolve_line_item_notes(stmt)
    return stmt


def _run_graph(pdf: Path, income_page: int | None = None, bs_page: int | None = None,
               max_retries: int = 2) -> dict:
    """Invoke the one pipeline graph and return its final state."""
    import uuid as _uuid
    graph = compiled_pipeline()
    config = {"configurable": {"thread_id": str(_uuid.uuid4())}}
    initial = {"pdf": str(pdf), "income_page": income_page, "bs_page": bs_page,
               "retries": 0, "max_retries": max_retries}
    return graph.invoke(initial, config)

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

@app.command("canonical-full")
def canonical_full(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
):
    """Full canonical pull (income + balance) via the pipeline graph."""
    logger.info("Running canonical-full for {} (income_page={}, bs_page={})", pdf.name, income_page, bs_page)
    final = _run_graph(pdf, income_page, bs_page)
    stmt = final.get("statement")
    if stmt is None:
        typer.echo(f"No statement extracted (route: {final.get('route')})", err=True)
        raise typer.Exit(code=1)
    typer.echo(stmt.model_dump_json(indent=2))

@app.command()
def validate(
    pdf: Path,
    income_page: int = typer.Option(None, "--income-page"),
    bs_page: int = typer.Option(None, "--bs-page"),
):
    """Full pipeline via the graph: resolve -> extract -> cross-foot -> retry -> confidence -> HITL gate."""
    logger.info("Running validate pipeline for {} (income_page={}, bs_page={})", pdf.name, income_page, bs_page)
    final = _run_graph(pdf, income_page, bs_page)
    report = final.get("report")
    if report is None:
        typer.echo(f"Pipeline produced no report (route: {final.get('route')})", err=True)
        raise typer.Exit(code=1)
    typer.echo(report.model_dump_json(indent=2))
    if final.get("route") == "hitl" or report.flagged_count:
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
    final = _run_graph(pdf, income_page, bs_page, max_retries)

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
    """Run all sample reports through the pipeline. Pages auto-resolve (resolver node)."""
    specs = [
        DocSpec("data/reports/AUSNET PTY LTD.pdf"),
        DocSpec("data/reports/B & E FOODS PTY LTD.pdf"),
        DocSpec("data/reports/CITIGROUP.pdf"),
        DocSpec("data/reports/YHI PTY LTD.pdf"),
    ]
    logger.info("Running batch pipeline for {} document(s) with max_retries={}", len(specs), max_retries)
    results = orchestrate(specs, max_retries)
    typer.echo(f"\n{'REPORT':30} {'ROUTE':10} {'RETRIES':8} {'FLAGGED':8}")
    for r in results:
        typer.echo(f"{Path(r.pdf).name:30} {r.route:10} {r.retries:<8} {r.flagged:<8}"
                   + (f"  ⚠ {r.error}" if r.error else ""))
    if any(r.route in ("hitl", "error") for r in results):
        raise typer.Exit(code=1)


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", "--host", help="Host for the FastAPI backend"),
    port: int = typer.Option(8000, "--port", help="Port for the FastAPI backend"),
):
    """Start both the FastAPI backend (uvicorn) and the Streamlit dashboard concurrently."""
    import subprocess
    import time

    logger.info("Starting API on http://{}:{} and Streamlit UI...", host, port)

    # Run using the virtual environment's Python executable
    api_cmd = [sys.executable, "-m", "uvicorn", "api.main:app", "--host", host, "--port", str(port)]
    ui_cmd = [sys.executable, "-m", "streamlit", "run", "src/finxtractor/dashboard.py"]

    processes = []
    try:
        api_proc = subprocess.Popen(api_cmd)
        processes.append(api_proc)
        # Give the API a brief moment to bind to the port
        time.sleep(1.5)

        ui_proc = subprocess.Popen(ui_cmd)
        processes.append(ui_proc)

        # Keep running until Ctrl+C or one of the processes exits
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received, stopping both processes...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        logger.info("Processes stopped successfully.")
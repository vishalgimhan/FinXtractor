from pathlib import Path
   
import typer, fitz

app = typer.Typer()

@app.command()
def run(pdf: Path):
    if not pdf.exists():
        raise typer.BadParameter(f"File {pdf} does not exist.")

    doc = fitz.open(pdf)
    typer.echo(f"Opened PDF: {pdf.name}, Number of pages: {doc.page_count}")

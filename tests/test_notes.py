from finxtractor.parsing.text import extract_pages
from finxtractor.parsing.routing import resolve_income_page
from finxtractor.parsing.docling_parser import parse_income_statement
from finxtractor.parsing.notes import resolve_line_item_notes
from finxtractor.parsing.note_tables import collect_note_tables

pdf = 'data/reports/CITIGROUP.pdf'

page, source = resolve_income_page(pdf, extract_pages(pdf))
print(f"income page: {page} (via {source})")

s = parse_income_statement(pdf, page)
resolve_line_item_notes(s)

notes = collect_note_tables(s, pdf)
for n, d in notes.items():
    print(f"Note {n}: page={d['page']} found={d['found']} rows={len(d['rows'])}")

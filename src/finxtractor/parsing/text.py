from dataclasses import dataclass
from pathlib import Path
import fitz

@dataclass
class Page:
    number: int
    text: str

def extract_pages(pdf: Path) -> list[Page]:
    doc = fitz.open(pdf)
    return [Page(i + 1, p.get_text()) for i, p in enumerate(doc)]
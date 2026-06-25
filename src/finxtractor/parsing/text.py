from dataclasses import dataclass
from pathlib import Path

from loguru import logger
import fitz

@dataclass
class Page:
    number: int
    text: str

def extract_pages(pdf: Path | str) -> list[Page]:
    pdf_path = Path(pdf)
    logger.info("Extracting pages from {}", pdf_path.name)
    doc = fitz.open(pdf_path)
    pages = [Page(i + 1, doc.load_page(i).get_text()) for i in range(doc.page_count)]
    logger.debug("Extracted {} page(s) from {}", len(pages), pdf_path.name)
    return pages
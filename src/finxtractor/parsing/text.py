from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..services.pdf_reader import get_pdf_reader

@dataclass
class Page:
    number: int
    text: str

def extract_pages(pdf: Path | str) -> list[Page]:
    pdf_path = Path(pdf)
    logger.info("Extracting pages from {}", pdf_path.name)
    texts = get_pdf_reader().page_texts(pdf)
    pages = [Page(i + 1, text) for i, text in enumerate(texts)]
    logger.debug("Extracted {} page(s) from {}", len(pages), pdf_path.name)
    return pages
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from ..config import get_param
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


def assess_text_layer(pages: list[Page]) -> str:
    """Classify a PDF's extractable text as 'ok' | 'sparse' | 'none'.
    Drives scanned-PDF routing (OCR / VLM). Thresholds live in param.yaml."""
    if not pages:
        return "none"
    per_page_min = get_param("triage", "per_page_min_chars", default=50)
    min_fraction = get_param("triage", "min_text_page_fraction", default=0.5)
    min_avg = get_param("triage", "min_chars_per_page", default=100)

    char_counts = [len(p.text.strip()) for p in pages]
    non_empty = sum(1 for c in char_counts if c >= per_page_min)
    fraction = non_empty / len(pages)
    avg = sum(char_counts) / len(pages)
    if non_empty == 0:
        return "none"
    return "ok" if (fraction >= min_fraction and avg >= min_avg) else "sparse"
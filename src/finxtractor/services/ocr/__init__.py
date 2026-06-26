"""OCR text backend: rasterize a page and read its text.

Used to give scanned PDFs (no text layer) something to match markers against
during page location. RapidOCR (onnxruntime, no system binary) is primary;
pytesseract is a fallback. Returns '' if no OCR engine is available.
"""
from functools import lru_cache
from pathlib import Path

from loguru import logger

from ..pdf_reader import get_pdf_reader

__all__ = ["ocr_page_text"]


@lru_cache(maxsize=1)
def _rapidocr():
    from rapidocr import RapidOCR     # lazy: optional dependency
    return RapidOCR()


def _to_array(png: bytes):
    import io
    import numpy as np
    from PIL import Image
    return np.array(Image.open(io.BytesIO(png)).convert("RGB"))


def _rapidocr_text(png: bytes) -> str:
    result = _rapidocr()(_to_array(png))
    txts = getattr(result, "txts", None)        # rapidocr v2
    if txts:
        return "\n".join(txts)
    if isinstance(result, tuple):               # older API: (lines, elapse)
        result = result[0]
    if result:
        return "\n".join(line[1] for line in result)
    return ""


def _tesseract_text(png: bytes) -> str:
    import io
    import pytesseract
    from PIL import Image
    return pytesseract.image_to_string(Image.open(io.BytesIO(png)))


def ocr_page_text(pdf: Path | str, page_number: int, dpi: int | None = None) -> str:
    """OCR one 1-based page to text. Tries RapidOCR then pytesseract; '' if both
    are unavailable or fail. `dpi` lets callers render coarser than the default —
    page location only needs legible headings, not clean figures, so a low DPI
    is much faster (OCR cost scales with pixel count)."""
    png = get_pdf_reader().render_page(pdf, page_number, dpi=dpi)
    for name, fn in (("rapidocr", _rapidocr_text), ("pytesseract", _tesseract_text)):
        try:
            text = fn(png)
            if text.strip():
                return text
        except Exception as e:
            logger.debug("OCR engine {} unavailable on page {}: {}", name, page_number, type(e).__name__)
    return ""

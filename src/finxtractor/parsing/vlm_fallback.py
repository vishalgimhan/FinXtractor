from pathlib import Path
from ..config import get_param
from ..schemas import Statement
from .docling_parser import parse_income_statement, table_confidence

# Vision model for the fallback route.
VLM_MODEL = "granite-docling"

def extract_with_vlm(pdf: Path | str, page_number: int) -> Statement:
    """Fallback extractor. STUB — wired but not implemented yet."""
    raise NotImplementedError(
        "VLM fallback not implemented"
    )

def extract_income_statement(pdf: Path | str, page_number: int) -> Statement:
    """Primary route with VLM fallback on low confidence."""
    stmt = parse_income_statement(pdf, page_number)
    score = table_confidence(stmt)
    floor = get_param("vlm", "confidence_floor", default=0.0)  # >0 arms the fallback
    if score < floor:
        return extract_with_vlm(pdf, page_number)
    return stmt
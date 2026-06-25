from pathlib import Path

from ..config import get_model
from ..schemas import Statement

# Vision model for the fallback route (config/models.yaml).
VLM_MODEL = get_model("vlm", default="granite-docling")


def extract_with_vlm(pdf: Path | str, page_number: int) -> Statement:
    """Fallback extractor. STUB — wired but not implemented yet."""
    raise NotImplementedError("VLM fallback not implemented")

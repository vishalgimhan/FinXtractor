"""Swappable vision-LLM fallback backends.

`get_vlm_extractor()` is the single entry point — it reads the active provider
from config/models.yaml (vlm.active) and builds a vision-capable chat model
using the very same Ollama / OpenRouter clients as services/llm, then wraps it
in the provider-agnostic VlmStatementExtractor.
"""
from functools import lru_cache
from pathlib import Path

from ...config import load_active_vlm
from ...schemas import Statement
from ..llm.ollama import build as _build_ollama
from ..llm.openrouter import build as _build_openrouter
from .base import VlmExtractor
from .extractor import VlmStatementExtractor

__all__ = ["VlmExtractor", "get_vlm_extractor", "extract_with_vlm"]

# VLM uses the same chat clients as the text LLM — only the model names differ.
_BUILDERS = {"ollama": _build_ollama, "openrouter": _build_openrouter}


@lru_cache(maxsize=1)
def get_vlm_extractor() -> VlmExtractor:
    active, cfg = load_active_vlm()
    build = _BUILDERS.get(active)
    if build is None:
        raise ValueError(f"Unknown VLM provider: {active}")
    return VlmStatementExtractor(build(cfg))


def extract_with_vlm(pdf: Path | str, page_number: int) -> Statement:
    """Convenience wrapper used by the extraction fallback path
    (parsing.statements.extract_statement)."""
    return get_vlm_extractor().extract(pdf, page_number)

"""Swappable chat-LLM provider backends.

`get_chat_model()` is the single entry point — it reads the active provider from
config/models.yaml (llm.active) and lazy-imports it, the same way
get_table_extractor() / get_pdf_reader() select their backends.
"""
from functools import lru_cache

from ...config import load_active_provider

__all__ = ["get_chat_model"]


@lru_cache(maxsize=1)
def get_chat_model():
    active, cfg = load_active_provider()
    if active == "ollama":
        from .ollama import build
        return build(cfg)
    if active == "openrouter":
        from .openrouter import build
        return build(cfg)
    raise ValueError(f"Unknown provider: {active}")

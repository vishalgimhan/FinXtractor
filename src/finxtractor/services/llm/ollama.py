"""Ollama (local) chat-LLM backend."""
from ...config import ProviderConfig


def build(cfg: ProviderConfig):
    # Lazy import so the core (alias/fuzzy) pipeline runs without the optional
    # langchain providers installed; only the LLM tier needs them.
    from langchain_ollama import ChatOllama
    return ChatOllama(model=cfg.model, base_url=cfg.base_url, temperature=cfg.temperature)

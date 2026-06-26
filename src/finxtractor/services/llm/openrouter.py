"""OpenRouter (hosted, OpenAI-compatible) chat-LLM backend."""
from ...config import ProviderConfig, get_env


def build(cfg: ProviderConfig):
    # Lazy import so the core (alias/fuzzy) pipeline runs without the optional
    # langchain providers installed; only the LLM tier needs them.
    from langchain_openai import ChatOpenAI
    api_key = get_env("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in .env or environment")
    return ChatOpenAI(model=cfg.model, base_url=cfg.base_url,
                      api_key=api_key, temperature=cfg.temperature)

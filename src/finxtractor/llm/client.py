from ..config import load_active_provider, get_env


def get_chat_model():
    # Imports are lazy so the core (alias/fuzzy) pipeline runs without the
    # optional langchain providers installed; only the LLM tier needs them.
    active, cfg = load_active_provider()
    if active == "ollama":
        from langchain_ollama import ChatOllama
        return ChatOllama(model=cfg.model, base_url=cfg.base_url,
                          temperature=cfg.temperature)
    if active == "openrouter":
        from langchain_openai import ChatOpenAI
        api_key = get_env("OPENROUTER_API_KEY")
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY not set in .env or environment")
        return ChatOpenAI(model=cfg.model, base_url=cfg.base_url,
                          api_key=api_key, temperature=cfg.temperature)
    raise ValueError(f"Unknown provider: {active}")
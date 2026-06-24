import os
from pathlib import Path
import yaml
from dotenv import load_dotenv, dotenv_values
from pydantic import BaseModel

load_dotenv()   # populate the environment from a local .env

_CONFIG_PATH = Path("config/llm.yaml")


def get_env(key: str, default: str | None = None) -> str | None:
    """Read a setting from .env (falling back to a real environment variable)."""
    return dotenv_values().get(key) or os.environ.get(key, default)


class ProviderConfig(BaseModel):
    model: str
    base_url: str
    temperature: float = 0.0


def load_active_provider() -> tuple[str, ProviderConfig]:
    raw = yaml.safe_load(_CONFIG_PATH.read_text())
    active = get_env("FINX_LLM_PROVIDER", raw["active"])   # .env overrides file
    return active, ProviderConfig(**raw["providers"][active])
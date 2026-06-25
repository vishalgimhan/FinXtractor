"""Project-wide configuration, usable from any module.

- secrets/env via .env (`get_env`)
- tunable parameters via config/param.yaml (`get_param`)
- LLM provider selection via config/llm.yaml (`load_active_provider`)
"""
import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv, dotenv_values
from pydantic import BaseModel

load_dotenv()   # populate the environment from a local .env

_CONFIG_DIR = Path("config")
_LLM_PATH = _CONFIG_DIR / "llm.yaml"
_PARAM_PATH = _CONFIG_DIR / "param.yaml"


# --- environment / secrets --------------------------------------------------
def get_env(key: str, default: str | None = None) -> str | None:
    """Read a setting from .env (falling back to a real environment variable)."""
    return dotenv_values().get(key) or os.environ.get(key, default)


# --- tunable parameters (config/param.yaml) ---------------------------------
@lru_cache(maxsize=1)
def load_params() -> dict:
    """Load config/param.yaml once. Missing file -> {} so callers fall back to defaults."""
    if _PARAM_PATH.exists():
        return yaml.safe_load(_PARAM_PATH.read_text()) or {}
    return {}


def get_param(*keys: str, default=None):
    """Nested lookup into param.yaml, e.g. get_param('parsing', 'do_ocr', default=False)."""
    node = load_params()
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


# --- LLM provider (config/llm.yaml) -----------------------------------------
class ProviderConfig(BaseModel):
    model: str
    base_url: str
    temperature: float = 0.0


def load_active_provider() -> tuple[str, ProviderConfig]:
    raw = yaml.safe_load(_LLM_PATH.read_text())
    active = get_env("FINX_LLM_PROVIDER", raw["active"])   # .env overrides file
    return active, ProviderConfig(**raw["providers"][active])

"""Project-wide configuration, usable from any module.

- secrets/env via .env (`get_env`)
- tunable parameters via config/param.yaml (`get_param`)
- LLM provider selection via config/llm.yaml (`load_active_provider`)
"""
import os
import re
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv, dotenv_values
from pydantic import BaseModel

load_dotenv()   # populate the environment from a local .env

_CONFIG_DIR = Path("config")
_PARAM_PATH = _CONFIG_DIR / "param.yaml"
_PATTERNS_PATH = _CONFIG_DIR / "patterns.yaml"
_MODELS_PATH = _CONFIG_DIR / "models.yaml"   # chat LLM provider + model names


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


# --- models (config/models.yaml: chat LLM provider + model names) -----------
@lru_cache(maxsize=1)
def load_models() -> dict:
    """Load config/models.yaml once. Missing file -> {} so callers fall back to defaults."""
    if _MODELS_PATH.exists():
        return yaml.safe_load(_MODELS_PATH.read_text()) or {}
    return {}


def get_model(name: str, default: str | None = None) -> str | None:
    """A named model from models.yaml (e.g. 'vlm'), or the default."""
    return load_models().get(name, default)


# --- markers & regex patterns (config/patterns.yaml) ------------------------
# Built-in defaults; config/patterns.yaml overrides any of these when present.
_DEFAULT_MARKERS: dict[str, list[str]] = {
    "income": [
        "statement of profit or loss",
        "statement of profit",
        "statement of comprehensive income",
        "statement of financial performance",
        "income statement",
    ],
    "balance_sheet": [
        "statement of financial position",
        "balance sheet",
        "consolidated statement of financial position",
    ],
    "notes": [
        "notes to the financial statements",
        "notes to and forming part of",
    ],
}

_DEFAULT_REGEX: dict[str, str] = {
    "year": r"\b(19|20)\d{2}\b",
    "number": r"\$|\d[\d,]{2,}",
    "standalone_int": r"^\s*(\d{1,3})\s*$",     # a printed page number, not a year
}


@lru_cache(maxsize=1)
def load_patterns() -> dict:
    """Load config/patterns.yaml once. Missing file -> {} so callers fall back to defaults."""
    if _PATTERNS_PATH.exists():
        return yaml.safe_load(_PATTERNS_PATH.read_text()) or {}
    return {}


def get_markers(name: str) -> list[str]:
    """A named marker list from patterns.yaml (e.g. 'income'), or its built-in default."""
    val = load_patterns().get("markers", {}).get(name)
    return val if val is not None else _DEFAULT_MARKERS.get(name, [])


def get_pattern(name: str) -> re.Pattern:
    """A named regex from patterns.yaml (e.g. 'year'), compiled, or its built-in default."""
    raw = load_patterns().get("regex", {}).get(name) or _DEFAULT_REGEX.get(name)
    if raw is None:
        raise KeyError(f"unknown regex pattern '{name}'")
    return re.compile(raw)


# --- LLM provider (config/models.yaml -> `llm` section) ---------------------
class ProviderConfig(BaseModel):
    model: str
    base_url: str
    temperature: float = 0.0


def load_active_provider() -> tuple[str, ProviderConfig]:
    llm = load_models().get("llm", {})
    active = get_env("FINX_LLM_PROVIDER", llm["active"])   # .env overrides file
    return active, ProviderConfig(**llm["providers"][active])


def load_active_vlm() -> tuple[str, ProviderConfig]:
    """Active vision-LLM provider for the VLM fallback (config/models.yaml -> vlm)."""
    vlm = load_models().get("vlm", {})
    active = get_env("FINX_VLM_PROVIDER", vlm["active"])   # .env overrides file
    return active, ProviderConfig(**vlm["providers"][active])


# --- table-extraction backend (config/models.yaml -> `table_extraction`) -----
def load_active_table_extractor() -> tuple[str, dict]:
    """Return (active backend name, its provider settings dict). Falls back to a
    docling default so the package runs without the models.yaml section."""
    te = load_models().get("table_extraction", {})
    active = get_env("FINX_TABLE_BACKEND", te.get("active", "docling"))
    cfg = te.get("providers", {}).get(active, {})
    return active, cfg


# --- PDF reader backend (config/models.yaml -> `pdf_reader`) -----------------
def load_active_pdf_reader() -> tuple[str, dict]:
    """Return (active backend name, its provider settings dict). Falls back to a
    pymupdf default so the package runs without the models.yaml section."""
    pr = load_models().get("pdf_reader", {})
    active = get_env("FINX_PDF_READER", pr.get("active", "pymupdf"))
    cfg = pr.get("providers", {}).get(active, {})
    return active, cfg

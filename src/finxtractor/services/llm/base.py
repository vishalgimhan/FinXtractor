"""Contract for chat-LLM provider backends.

Each provider module exposes `build(cfg) -> BaseChatModel`, returning a
configured langchain chat model. The factory in __init__ selects one from
config/models.yaml (llm.active), mirroring the table-extractor / pdf-reader
backends.
"""
from __future__ import annotations

from typing import Protocol

from ...config import ProviderConfig


class ChatModelBuilder(Protocol):
    """A provider module's `build` function."""

    def __call__(self, cfg: ProviderConfig):
        ...

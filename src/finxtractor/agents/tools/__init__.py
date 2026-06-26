"""Agent tools: thin, LLM-callable wrappers over the deterministic functions.

Tools are built by a factory bound to a context object so the heavy data they
operate on (page texts, the PDF, the page index) stays in the closure and never
enters the LLM's context — only compact results (page numbers, sources, counts)
are returned to the model.
"""
from .resolver import ResolverContext, build_resolver_tools

__all__ = ["ResolverContext", "build_resolver_tools"]

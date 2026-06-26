from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from .state import PipelineState
from .nodes import resolver_agent, extractor_agent, validator_node, retry_node, hitl_node, scoring_node
from .vlm_node import vlm_node
from .router import (
    route_after_resolver, route_after_vlm, route_after_extractor, route_after_validation,
)


def build_pipeline() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("resolver", resolver_agent)
    g.add_node("extractor", extractor_agent)
    g.add_node("vlm", vlm_node)             # shared vision tier (locate + extract)
    g.add_node("validator", validator_node)
    g.add_node("retry", retry_node)
    g.add_node("hitl", hitl_node)
    g.add_node("scoring", scoring_node)

    g.add_edge(START, "resolver")           # entry: locate the statement pages
    g.add_conditional_edges(                # located -> extract; still missing -> vlm; else HITL
        "resolver",
        route_after_resolver,
        {"extract": "extractor", "vlm": "vlm", "unresolved": "hitl"},
    )
    g.add_conditional_edges(                # vlm returns to whoever it served
        "vlm",
        route_after_vlm,
        {"extractor": "extractor", "validator": "validator", "hitl": "hitl"},
    )
    g.add_conditional_edges(                # text tiers done -> validate; unreadable page -> vlm
        "extractor",
        route_after_extractor,
        {"vlm": "vlm", "validate": "validator"},
    )

    g.add_conditional_edges(
        "validator",
        route_after_validation,
        {"retry": "retry", "hitl": "hitl", "proceed": "scoring"},
    )

    g.add_edge("retry", "extractor")        # retry re-extracts only (pages already resolved)
    g.add_edge("hitl", END)                 # HITL terminates this run
    g.add_edge("scoring", END)              # proceed terminates this run
    return g

def compiled_pipeline(checkpointer=None):
    """Compile the graph. Pass a checkpointer for resumable, inspectable runs."""
    return build_pipeline().compile(checkpointer=checkpointer or InMemorySaver())
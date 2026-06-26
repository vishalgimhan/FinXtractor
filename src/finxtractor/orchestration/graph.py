from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from .state import PipelineState
from .nodes import resolver_agent, extractor_node, validator_node, retry_node, hitl_node, scoring_node
from .router import route_after_resolver, route_after_validation


def build_pipeline() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("resolver", resolver_agent)
    g.add_node("extractor", extractor_node)
    g.add_node("validator", validator_node)
    g.add_node("retry", retry_node)
    g.add_node("hitl", hitl_node)
    g.add_node("scoring", scoring_node)

    g.add_edge(START, "resolver")           # entry: locate the statement pages
    g.add_conditional_edges(                # located -> extract; not found -> graceful HITL
        "resolver",
        route_after_resolver,
        {"extract": "extractor", "unresolved": "hitl"},
    )
    g.add_edge("extractor", "validator")    # always validate after extracting

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
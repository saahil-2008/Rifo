"""LangGraph verification pipeline builder.

Constructs the fixed graph with explicit conditional edges per PRD §FR-5.
This is NOT a ReAct agent — every edge is predetermined by routing functions.

Graph topology:
  START → vision_extract → [checkable?] → embed_claim → cache_probe
    → [cached?] → factcheck_hit → [hit?] → retrieve → nli_stance
    → aggregate → [insufficient & retry=0?] → explain → localize → END
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.models.state import PipelineState
from app.graph.nodes.vision_extract import vision_extract
from app.graph.nodes.embed_claim import embed_claim
from app.graph.nodes.cache_probe import cache_probe
from app.graph.nodes.factcheck_hit import factcheck_hit
from app.graph.nodes.retrieve import retrieve
from app.graph.nodes.nli_stance import nli_stance
from app.graph.nodes.aggregate import aggregate
from app.graph.nodes.explain import explain
from app.graph.nodes.localize import localize
from app.graph.routing import (
    route_after_vision,
    route_after_cache,
    route_after_factcheck,
    route_after_aggregate,
)

logger = logging.getLogger(__name__)


def build_verification_graph(entry_node: str = "vision_extract") -> StateGraph:
    """Build and compile the verification pipeline graph.

    Returns the compiled graph ready for invocation via `graph.ainvoke(state)`
    or streaming via `graph.astream(state)`.

    `entry_node` exists so tests can start the graph after vision extraction
    (e.g. `entry_node="embed_claim"`) and exercise the cache/retrieve/NLI/
    aggregate/persist logic without a vision API call.
    """
    graph = StateGraph(PipelineState)

    # ── Register all nodes ──
    graph.add_node("vision_extract", vision_extract)
    graph.add_node("embed_claim", embed_claim)
    graph.add_node("cache_probe", cache_probe)
    graph.add_node("factcheck_hit", factcheck_hit)
    graph.add_node("retrieve", retrieve)
    graph.add_node("nli_stance", nli_stance)
    graph.add_node("aggregate", aggregate)
    graph.add_node("explain", explain)
    graph.add_node("localize", localize)

    # ── Entry point ──
    graph.set_entry_point(entry_node)

    # ── Conditional edges ──

    # After vision_extract: if not checkable → END, else → embed_claim
    graph.add_conditional_edges(
        "vision_extract",
        route_after_vision,
        {"embed_claim": "embed_claim", END: END},
    )

    # embed_claim always flows to cache_probe
    graph.add_edge("embed_claim", "cache_probe")

    # After cache_probe: if cache hit → END, else → factcheck_hit
    graph.add_conditional_edges(
        "cache_probe",
        route_after_cache,
        {"factcheck_hit": "factcheck_hit", END: END},
    )

    # After factcheck_hit: if hit → aggregate (skip retrieve+nli), else → retrieve
    graph.add_conditional_edges(
        "factcheck_hit",
        route_after_factcheck,
        {"retrieve": "retrieve", "aggregate": "aggregate"},
    )

    # retrieve always flows to nli_stance
    graph.add_edge("retrieve", "nli_stance")

    # nli_stance always flows to aggregate
    graph.add_edge("nli_stance", "aggregate")

    # After aggregate: if insufficient & retry_count==1 → retrieve, else → explain
    graph.add_conditional_edges(
        "aggregate",
        route_after_aggregate,
        {"retrieve": "retrieve", "explain": "explain"},
    )

    # explain always flows to localize
    graph.add_edge("explain", "localize")

    # localize → END
    graph.add_edge("localize", END)

    logger.info("Verification graph built: 9 nodes, 4 conditional edges")

    return graph.compile()

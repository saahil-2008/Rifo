"""Conditional edge routing functions for the LangGraph pipeline.

These functions inspect the current PipelineState and return the name
of the next node (or END). They implement the fixed graph topology
described in PRD §FR-5 — no ReAct, no tool-choosing.
"""

from __future__ import annotations

import logging
from typing import Literal

from langgraph.graph import END

from app.models.state import PipelineState

logger = logging.getLogger(__name__)


def route_after_vision(state: PipelineState) -> Literal["embed_claim", "__end__"]:
    """After vision_extract: short-circuit if not checkable."""
    if not state.get("checkable", False):
        logger.info("routing: claim not checkable → END (no_claim_found)")
        return END
    return "embed_claim"


def route_after_cache(state: PipelineState) -> Literal["factcheck_hit", "__end__"]:
    """After cache_probe: return cached result or continue to factcheck."""
    if state.get("cached", False):
        logger.info("routing: cache hit → END (serve cached)")
        return END
    return "factcheck_hit"


def route_after_factcheck(state: PipelineState) -> Literal["retrieve", "aggregate"]:
    """After factcheck_hit: skip retrieval if factcheck found a match.

    A factcheck hit means evidence_items already has high-quality items
    with stances derived from ClaimReview ratings. Skip retrieve + nli_stance
    and go directly to aggregate.
    """
    evidence = state.get("evidence_items", [])
    # If factcheck populated evidence with stance data, skip to aggregate
    has_factcheck_evidence = any(
        item.get("stance") and item.get("stance") != ""
        for item in evidence
    )
    if has_factcheck_evidence:
        logger.info("routing: factcheck hit with %d evidence items → aggregate", len(evidence))
        return "aggregate"
    return "retrieve"


def route_after_aggregate(state: PipelineState) -> Literal["retrieve", "explain"]:
    """After aggregate: retry once on insufficient, otherwise explain.

    Hard cap: one retry (constraint #17). `aggregate` sets `retry_requested`
    explicitly on every pass — True to loop back to `retrieve` with a broadened
    query, False once a final verdict exists. Keying on that flag (instead of a
    lingering `retry_count`) prevents the retry edge from looping forever on a
    final `insufficient` verdict.
    """
    if state.get("retry_requested", False):
        logger.info("routing: aggregate requested a retry → retrieve")
        return "retrieve"

    return "explain"

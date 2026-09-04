"""Aggregation node (FR-6).

Deterministic rules — no model call. Weights each stance by the
credibility score of its source domain, then applies the verdict taxonomy.

This node contains REAL logic even in Milestone 1 because it is purely
deterministic and does not depend on external services.

On its FINAL pass (no retry requested) the node persists the claim, verdict,
and evidence rows so later identical claims hit the vector cache (PRD §FR-5,
§FR-8). The verdict row is written with a NULL explanation (constraint #14) —
the `explain` node backfills it. A DB failure never kills the live verdict:
it is logged and the verdict is returned uncached.

Retry semantics: aggregate signals a retry with an explicit `retry_requested`
flag rather than by leaving `retry_count` in a magic state. Every return sets
the flag explicitly (True to loop back to `retrieve`, False to proceed to
`explain`), because LangGraph merges state by key — an absent key would keep
the previous pass's value.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.state import PipelineState
from app.db import claims as claims_db
from app.db import verdicts as verdicts_db
from app.db import evidence as evidence_db

logger = logging.getLogger(__name__)

# ── Default credibility for unknown domains ──
DEFAULT_CREDIBILITY = 0.4

# ── Thresholds ──
MIN_SOURCES_FOR_VERDICT = 1
CREDIBILITY_FLOOR = 0.3
MANIPULATED_DATE_GAP_DAYS = 30  # image predates claimed context by this much


async def _finalize(
    state: PipelineState,
    stances: list,
    label: str,
    confidence: float,
) -> PipelineState:
    """Persist the final verdict (claim + verdict + evidence) and return state.

    Runs only on the final aggregate pass. Any DB failure is logged and the
    verdict is still returned so the live response is not blocked on storage.
    """
    claim_id = None
    verdict_id = None

    claim = state.get("claim", "")
    embedding = state.get("embedding", []) or []

    # Only persist when we have a real claim and a real embedding. A zero
    # vector (embedding failure) must never be cached — it could collide with
    # other failed embeddings.
    if claim and any(embedding):
        try:
            claim_id = await claims_db.insert_claim(
                text=claim,
                text_original=state.get("claim_original", "") or None,
                lang=state.get("source_lang", "en"),
                embedding=embedding,
            )
            verdict_id = await verdicts_db.insert_verdict(
                claim_id=claim_id,
                label=label,
                confidence=round(confidence, 2),
                explanation=None,  # written later by explain (constraint #14)
                earliest_url=state.get("earliest_url", "") or None,
                earliest_date=state.get("earliest_date", "") or None,
                is_breaking=True,
            )
            if stances and verdict_id:
                await evidence_db.insert_evidence(verdict_id, stances)
        except Exception as e:
            logger.exception("aggregate: persistence failed — serving uncached verdict: %s", e)

    out: dict = {
        "label": label,
        "confidence": round(confidence, 2),
        "retry_requested": False,
    }
    if claim_id is not None:
        out["claim_id"] = claim_id
    if verdict_id is not None:
        out["verdict_id"] = verdict_id
    return out


async def aggregate(state: PipelineState) -> PipelineState:
    """Apply deterministic aggregation rules to produce a verdict.

    Rules (PRD §FR-6):
    - refutes dominant, credible sources          → fake
    - supports dominant, credible sources         → genuine
    - support and refute both present, mixed      → misleading
    - image earliest publication predates claimed
      context by a wide margin                    → manipulated
    - top evidence credibility-weighted score
      below floor, or fewer than 2 sources        → insufficient

    manipulated takes precedence over genuine.
    """
    # `stances` is the NLI output on the retrieve path; on the factcheck
    # short-circuit path (nli_stance skipped) items already carry stances and
    # live in evidence_items. Fall back so aggregate never sees an empty set
    # when evidence exists.
    stances = state.get("stances") or state.get("evidence_items", [])
    retry_count = state.get("retry_count", 0)

    logger.info("aggregate: processing %d stanced evidence items", len(stances))

    if len(stances) < MIN_SOURCES_FOR_VERDICT:
        # Not enough evidence
        if retry_count == 0:
            logger.info("aggregate: insufficient evidence, scheduling one retry")
            return {
                "label": "insufficient",
                "confidence": 0.0,
                "retry_count": 1,
                "retry_requested": True,
            }
        logger.info("aggregate: insufficient evidence after retry, final verdict")
        return await _finalize(state, stances, "insufficient", 0.3)

    # ── Compute weighted stance scores ──
    weighted_support = 0.0
    weighted_refute = 0.0
    total_credibility = 0.0

    for item in stances:
        cred = item.get("credibility", DEFAULT_CREDIBILITY)
        stance_score = item.get("stance_score", 0.5)
        stance = item.get("stance", "neutral")

        weight = cred * stance_score

        if stance == "supports":
            weighted_support += weight
        elif stance == "refutes":
            weighted_refute += weight

        total_credibility += cred

    # ── Check for manipulated image (takes precedence over genuine) ──
    earliest_date_str = state.get("earliest_date", "")
    is_manipulated = False
    if earliest_date_str:
        try:
            earliest = datetime.fromisoformat(earliest_date_str.replace("Z", "+00:00"))
            gap = (datetime.now(timezone.utc) - earliest).days
            if gap >= MANIPULATED_DATE_GAP_DAYS:
                is_manipulated = True
        except (ValueError, TypeError):
            pass

    # ── Determine verdict ──
    avg_credibility = total_credibility / len(stances) if stances else 0.0

    if avg_credibility < CREDIBILITY_FLOOR:
        label = "insufficient"
        confidence = avg_credibility
    elif is_manipulated and weighted_support > weighted_refute:
        # manipulated takes precedence over genuine
        label = "manipulated"
        confidence = min(0.95, 0.7 + avg_credibility * 0.3)
    elif weighted_refute > weighted_support * 1.5:
        label = "fake"
        confidence = min(0.99, weighted_refute / (weighted_refute + weighted_support + 0.01))
    elif weighted_support > weighted_refute * 1.5:
        label = "genuine"
        confidence = min(0.99, weighted_support / (weighted_support + weighted_refute + 0.01))
    elif weighted_support > 0 and weighted_refute > 0:
        label = "misleading"
        confidence = min(0.85, 0.5 + abs(weighted_support - weighted_refute) * 0.2)
    else:
        label = "insufficient"
        confidence = 0.3

    # First pass that lands on insufficient → retry once with a broadened query
    if label == "insufficient" and retry_count == 0:
        logger.info("aggregate: insufficient verdict, retrying once")
        return {
            "label": label,
            "confidence": round(confidence, 2),
            "retry_count": 1,
            "retry_requested": True,
        }

    logger.info("aggregate: verdict=%s confidence=%.2f", label, confidence)
    return await _finalize(state, stances, label, confidence)

"""Vector cache probe node.

Performs a pgvector cosine similarity search against claims.embedding.
Threshold: 0.93 (deliberately tight — PRD §FR-5 and constraint #24).

On hit: increments check_count, returns cached verdict + evidence + explanation.
On miss: continues to factcheck_hit.
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.db.claims import find_similar, increment_check_count
from app.db.evidence import get_evidence_by_verdict_id

logger = logging.getLogger(__name__)


async def cache_probe(state: PipelineState) -> PipelineState:
    """Probe the vector cache for a semantically similar claim.

    Uses pgvector cosine similarity with threshold 0.93.
    On hit, serves the cached verdict without retrieval or explanation
    generation (constraint #15).
    """
    embedding = state.get("embedding", [])

    if not embedding:
        logger.warning("cache_probe: no embedding available, treating as miss")
        return {"cached": False, "claim_id": 0, "check_count": 1}

    try:
        # find_similar is async — must be awaited exactly once. The previous
        # sync-then-await double call returned an unawaited coroutine and
        # crashed on subscript. (PRD §FR-5)
        result = await find_similar(embedding)
    except Exception as e:
        logger.warning("cache_probe: DB query failed, treating as miss: %s", e)
        result = None

    if result is None:
        logger.info("cache_probe: cache miss")
        return {"cached": False, "claim_id": 0, "check_count": 1}

    # ── Cache hit ──
    claim_id = result["claim_id"]
    verdict_id = result["verdict_id"]

    # Increment check_count atomically
    new_count = await increment_check_count(claim_id)

    # Fetch cached evidence
    evidence_items = await get_evidence_by_verdict_id(verdict_id)

    logger.info(
        "cache_probe: cache hit claim_id=%d verdict=%s check_count=%d",
        claim_id,
        result["label"],
        new_count,
    )

    return {
        "cached": True,
        "claim_id": claim_id,
        "verdict_id": verdict_id,
        "label": result["label"],
        "confidence": result["confidence"],
        "check_count": new_count,
        "first_seen": result["first_seen"].isoformat() if result.get("first_seen") else "",
        "explanation": result.get("explanation", ""),
        "evidence_items": evidence_items,
        "stances": evidence_items,  # already has stances from DB
        "earliest_url": result.get("earliest_url", ""),
        "earliest_date": result.get("earliest_date", ""),
    }

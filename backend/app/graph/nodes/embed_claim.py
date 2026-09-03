"""Claim embedding node.

Embeds the normalized English claim using multilingual-e5-small (384-dim).
Local inference, no network call, ~20 ms.

The E5 model family requires a "query: " prefix on input for optimal
retrieval performance.
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.services.ml_models import embed_text

logger = logging.getLogger(__name__)


async def embed_claim(state: PipelineState) -> PipelineState:
    """Embed the English-normalized claim using multilingual-e5-small."""
    claim = state.get("claim", "")
    logger.info("embed_claim: embedding claim '%s' (%d chars)", claim[:60], len(claim))

    try:
        embedding = embed_text(claim)
        logger.info("embed_claim: generated %d-dim embedding", len(embedding))
        return {"embedding": embedding}
    except Exception as e:
        logger.error("embed_claim: embedding failed: %s", e)
        # Return zero vector as fallback — cache probe will miss
        return {"embedding": [0.0] * 384}

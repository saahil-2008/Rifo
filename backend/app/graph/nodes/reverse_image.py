"""Reverse image search helper.

Calls the SerpApi Google Lens endpoint to find earlier instances of an image.
Runs ONLY when has_image_content is true, and ONLY inside the same
asyncio.gather as retrieve (constraint #19) — never as a sequential step.

This is a helper invoked from the retrieve node's gather, not a registered
LangGraph node. Returns the earliest publication date + URL for the aggregate
node's `manipulated` evaluation.
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.services import serpapi_lens

logger = logging.getLogger(__name__)


async def reverse_image_search(state: PipelineState) -> PipelineState:
    """Reverse-image search for earlier instances of the on-screen image.

    Degrades to no results (rather than raising) when there is no SerpApi key
    or the lookup fails, so the image leg never blocks the text verdict.
    """
    image_b64 = state.get("image_b64", "")

    if not image_b64:
        logger.warning("reverse_image_search: no image data to search")
        return {"earliest_url": "", "earliest_date": ""}

    logger.info("reverse_image_search: querying Google Lens (%d bytes b64)", len(image_b64))
    try:
        result = await serpapi_lens.reverse_image_search(image_b64)
    except Exception as e:
        logger.error("reverse_image_search: failed: %s", e)
        return {"earliest_url": "", "earliest_date": ""}

    return {
        "earliest_url": result.get("earliest_url", ""),
        "earliest_date": result.get("earliest_date", ""),
    }

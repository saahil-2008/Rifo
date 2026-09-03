"""Vision extraction node (FR-4).

Receives the full screenshot, calls Gemini 2.0 Flash to extract the single
most prominent checkable claim. Returns structured JSON with claim text,
original-language text, language code, content type, and whether image
content is present.

If checkable is false, short-circuits with no_claim_found error.
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.services.vision_client import extract_claim_from_image

logger = logging.getLogger(__name__)


async def vision_extract(state: PipelineState) -> PipelineState:
    """Extract a checkable claim from the screenshot via Gemini 2.0 Flash.

    Calls the vision model with JSON schema constraint and returns
    the extraction result directly as state updates.
    """
    image_b64 = state.get("image_b64", "")
    logger.info("vision_extract: processing screenshot (%d bytes b64)", len(image_b64))

    if not image_b64:
        logger.error("vision_extract: no image data provided")
        return {
            "checkable": False,
            "error_code": "upload_failed",
            "error_message": "No image data provided",
        }

    try:
        result = await extract_claim_from_image(image_b64)

        return {
            "claim": result.get("claim", ""),
            "claim_original": result.get("claim_original", ""),
            "source_lang": result.get("source_lang", "en"),
            "content_type": result.get("content_type", "other"),
            "has_image_content": result.get("has_image_content", False),
            "checkable": result.get("checkable", False),
        }

    except Exception as e:
        logger.exception("vision_extract: extraction failed: %s", e)
        return {
            "checkable": False,
            "error_code": "timeout",
            "error_message": f"Vision extraction failed: {e}",
        }

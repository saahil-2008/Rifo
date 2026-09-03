"""Gemini 2.0 Flash vision client for claim extraction (FR-4).

Sends the screenshot to Gemini with a JSON-constrained prompt.
Uses response_mime_type + response_schema for structured output.
Fast tier only — never route vision through flagship models.
"""

from __future__ import annotations

import base64
import json
import logging

import google.generativeai as genai

from app.config import settings

logger = logging.getLogger(__name__)

# ── JSON schema for structured extraction ──
EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "claim": {
            "type": "string",
            "description": "The single most prominent checkable claim, normalized to English",
        },
        "claim_original": {
            "type": "string",
            "description": "The claim in its original source language",
        },
        "source_lang": {
            "type": "string",
            "description": "BCP-47 language code of the source text (e.g. hi, ta, bn, en)",
        },
        "content_type": {
            "type": "string",
            "enum": [
                "text_message",
                "news_article",
                "social_post",
                "image_with_caption",
                "image_only",
                "other",
            ],
        },
        "has_image_content": {
            "type": "boolean",
            "description": "True when a photograph or graphic is present that warrants reverse image search",
        },
        "checkable": {
            "type": "boolean",
            "description": "False for opinion, greetings, personal conversation, or anything with no verifiable assertion",
        },
    },
    "required": [
        "claim",
        "claim_original",
        "source_lang",
        "content_type",
        "has_image_content",
        "checkable",
    ],
}

# ── System prompt ──
EXTRACTION_PROMPT = """You are a misinformation analysis system. Analyze the screenshot and extract the single most prominent, checkable factual claim.

Rules:
1. Extract EXACTLY ONE primary checkable claim — not an array, not multiple claims.
2. Normalize the claim to English in the "claim" field.
3. Preserve the original source-language wording in "claim_original".
4. If multiple candidate claims appear, select the most prominent and most checkable.
5. Set "checkable" to false for opinions, greetings, personal conversations, or anything without a verifiable factual assertion.
6. Set "has_image_content" to true only when a photograph or graphic is present that itself warrants reverse image search (not UI elements, not emojis).
7. Identify the content type based on the visual layout.

Return valid JSON matching the schema."""


def _configure_client() -> None:
    """Configure the Gemini client with the API key."""
    genai.configure(api_key=settings.gemini_api_key)


async def extract_claim_from_image(image_b64: str) -> dict:
    """Extract a checkable claim from a screenshot via Gemini 2.0 Flash.

    Args:
        image_b64: Base64-encoded JPEG screenshot.

    Returns:
        Dict with keys: claim, claim_original, source_lang, content_type,
        has_image_content, checkable.

    Raises:
        ValueError: If the response cannot be parsed as valid JSON.
    """
    _configure_client()

    model = genai.GenerativeModel(
        model_name=settings.vision_model,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=EXTRACTION_SCHEMA,
            temperature=0.1,  # low temperature for deterministic extraction
        ),
    )

    # Decode base64 to bytes for the vision API
    image_bytes = base64.b64decode(image_b64)

    # Build the multimodal content
    response = await model.generate_content_async(
        [
            EXTRACTION_PROMPT,
            {"mime_type": "image/jpeg", "data": image_bytes},
        ],
    )

    # Parse the JSON response
    try:
        result = json.loads(response.text)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("vision_client: failed to parse response: %s", response.text[:200])
        raise ValueError(f"Vision model returned invalid JSON: {e}") from e

    logger.info(
        "vision_client: extracted claim='%s' lang=%s checkable=%s",
        result.get("claim", "")[:60],
        result.get("source_lang", "?"),
        result.get("checkable", "?"),
    )

    return result

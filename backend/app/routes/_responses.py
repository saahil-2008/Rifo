"""Shared mapping helpers for API responses (PRD §8).

Both the WS/sync verify handlers and GET /v1/claim/{id} produce the same
VerdictResponse shape from slightly different source dictionaries (LangGraph
state vs. DB rows). Building them in one place keeps the field mapping
consistent: claims.text → claim, claims.text_original → claim_original,
claims.lang → source_lang.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.schemas import EvidenceItemResponse, VerdictResponse

logger = logging.getLogger(__name__)


def evidence_response(items: list[dict] | None) -> list[EvidenceItemResponse]:
    """Convert stanced evidence items (LangGraph state or DB rows) to response models."""
    return [
        EvidenceItemResponse(
            url=item.get("url", ""),
            domain=item.get("domain", ""),
            title=item.get("title", ""),
            snippet=item.get("snippet", ""),
            stance=item.get("stance", "neutral"),
            stance_score=item.get("stance_score", 0.0),
            published_at=item.get("published_at"),
            credibility=item.get("credibility", 0.4),
        )
        for item in (items or [])
    ]


def _iso(value) -> str:
    """Normalize a datetime/string to an ISO string."""
    if value is None or value == "":
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def verdict_response_from_state(state: dict, cached: bool | None = None) -> VerdictResponse:
    """Build a VerdictResponse from a LangGraph state dict or a DB row dict.

    The dict is expected to carry the claim/verdict/evidence keys used across
    the graph and the db helpers (see verdicts.get_full_verdict for the DB row
    shape). `explanation` prefers the localized form when present.
    """
    evidence = state.get("stances") or state.get("evidence_items") or []
    explanation = (
        state.get("explanation_localized")
        or state.get("explanation")
        or ""
    )

    return VerdictResponse(
        claim_id=state.get("claim_id", 0),
        claim=state.get("claim", "") or state.get("text", ""),
        claim_original=state.get("claim_original", "") or state.get("text_original", "") or "",
        source_lang=state.get("source_lang", "") or state.get("lang", "") or "en",
        label=state.get("label", "insufficient"),
        confidence=state.get("confidence", 0.0),
        check_count=state.get("check_count", 1),
        first_seen=_iso(state.get("first_seen")),
        cached=state.get("cached", False) if cached is None else cached,
        evidence=evidence_response(evidence),
        explanation=explanation,
    )

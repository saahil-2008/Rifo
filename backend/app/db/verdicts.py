"""Verdicts table CRUD operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from app.db import database
from app.config import settings

logger = logging.getLogger(__name__)


async def insert_verdict(
    claim_id: int,
    label: str,
    confidence: float,
    explanation: str | None = None,
    earliest_url: str | None = None,
    earliest_date: str | None = None,
    is_breaking: bool = True,
) -> int:
    """Insert a new verdict and return its ID.

    explanation is nullable at insert time because the verdict is emitted
    before the explanation is generated (constraint #14).

    TTL: breaking news = 6 hours, settled = 30 days.
    """
    if is_breaking:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.cache_ttl_breaking_hours)
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.cache_ttl_settled_days)

    query = """
        INSERT INTO verdicts (claim_id, label, confidence, explanation,
                              earliest_url, earliest_date, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
    """

    # Parse earliest_date if provided
    ed = None
    if earliest_date:
        try:
            ed = datetime.fromisoformat(earliest_date.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    async with database.pool.acquire() as conn:
        verdict_id = await conn.fetchval(
            query, claim_id, label, confidence, explanation,
            earliest_url, ed, expires_at,
        )

    logger.info("verdicts: inserted verdict_id=%d label=%s for claim_id=%d", verdict_id, label, claim_id)
    return verdict_id


async def get_verdict_by_claim_id(claim_id: int) -> dict | None:
    """Fetch the active (non-expired) verdict for a claim."""
    query = """
        SELECT id, claim_id, label, confidence, explanation,
               earliest_url, earliest_date, created_at, expires_at
        FROM verdicts
        WHERE claim_id = $1 AND expires_at > NOW()
        ORDER BY created_at DESC
        LIMIT 1
    """

    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(query, claim_id)

    return dict(row) if row else None


async def update_explanation(verdict_id: int, explanation: str) -> None:
    """Update the explanation on an existing verdict row.

    Called after the explanation is generated (post-verdict).
    """
    query = "UPDATE verdicts SET explanation = $1 WHERE id = $2"

    async with database.pool.acquire() as conn:
        await conn.execute(query, explanation, verdict_id)

    logger.info("verdicts: updated explanation for verdict_id=%d", verdict_id)


async def get_full_verdict(claim_id: int) -> dict | None:
    """Fetch full verdict with claim data for the /v1/claim/{id} endpoint."""
    query = """
        SELECT
            c.id AS claim_id,
            c.text AS claim,
            c.text_original AS claim_original,
            c.lang AS source_lang,
            c.check_count,
            c.first_seen,
            v.id AS verdict_id,
            v.label,
            v.confidence,
            v.explanation,
            v.earliest_url,
            v.earliest_date,
            v.created_at,
            v.expires_at
        FROM claims c
        JOIN verdicts v ON v.claim_id = c.id
        WHERE c.id = $1
        ORDER BY v.created_at DESC
        LIMIT 1
    """

    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(query, claim_id)

    return dict(row) if row else None

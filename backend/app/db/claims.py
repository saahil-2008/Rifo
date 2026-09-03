"""Claims table CRUD operations.

Handles claim insertion, pgvector cosine similarity search, and check_count
updates. The embedding column is the sole cache key — no hashing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db import database
from app.config import settings

logger = logging.getLogger(__name__)


async def find_similar(embedding: list[float], threshold: float | None = None) -> dict | None:
    """Find a semantically similar claim via pgvector cosine similarity.

    Threshold defaults to settings.cache_similarity_threshold (0.93).
    Only returns claims with a non-expired active verdict.

    Returns:
        dict with claim + verdict data if cache hit, else None.
    """
    if threshold is None:
        threshold = settings.cache_similarity_threshold

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
            1 - (c.embedding <=> $1::vector) AS similarity
        FROM claims c
        JOIN verdicts v ON v.claim_id = c.id
        WHERE 1 - (c.embedding <=> $1::vector) >= $2
          AND v.expires_at > NOW()
        ORDER BY similarity DESC
        LIMIT 1
    """

    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(query, vec_str, threshold)

    if row is None:
        return None

    logger.info(
        "cache_probe: hit claim_id=%d similarity=%.4f",
        row["claim_id"],
        row["similarity"],
    )

    return dict(row)


async def insert_claim(
    text: str,
    text_original: str,
    lang: str,
    embedding: list[float],
) -> int:
    """Insert a new claim and return its ID."""
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"

    query = """
        INSERT INTO claims (text, text_original, lang, embedding)
        VALUES ($1, $2, $3, $4::vector)
        RETURNING id
    """

    async with database.pool.acquire() as conn:
        claim_id = await conn.fetchval(query, text, text_original, lang, vec_str)

    logger.info("claims: inserted claim_id=%d text='%s'", claim_id, text[:60])
    return claim_id


async def increment_check_count(claim_id: int) -> int:
    """Atomically increment check_count and return the new value."""
    query = """
        UPDATE claims
        SET check_count = check_count + 1
        WHERE id = $1
        RETURNING check_count
    """

    async with database.pool.acquire() as conn:
        new_count = await conn.fetchval(query, claim_id)

    logger.info("claims: incremented check_count for claim_id=%d → %d", claim_id, new_count)
    return new_count

"""Evidence table CRUD operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db import database

logger = logging.getLogger(__name__)


async def insert_evidence(verdict_id: int, items: list[dict]) -> None:
    """Bulk insert evidence items for a verdict."""
    if not items:
        return

    query = """
        INSERT INTO evidence (verdict_id, url, domain, title, snippet,
                              stance, stance_score, published_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """

    async with database.pool.acquire() as conn:
        for item in items:
            pub_at = None
            if item.get("published_at"):
                try:
                    pub_at = datetime.fromisoformat(
                        item["published_at"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            await conn.execute(
                query,
                verdict_id,
                item.get("url", ""),
                item.get("domain", ""),
                item.get("title", ""),
                item.get("snippet", ""),
                item.get("stance", "neutral"),
                item.get("stance_score", 0.0),
                pub_at,
            )

    logger.info("evidence: inserted %d items for verdict_id=%d", len(items), verdict_id)


async def get_evidence_by_verdict_id(verdict_id: int) -> list[dict]:
    """Fetch all evidence items for a verdict.

    Resolves each item's credibility from the seeded `sources` table via a
    LEFT JOIN so cache-hit responses carry the same weights the aggregate node
    used when the verdict was first produced. Unrated domains fall back to 0.4.
    """
    query = """
        SELECT e.url, e.domain, e.title, e.snippet,
               e.stance, e.stance_score, e.published_at,
               COALESCE(s.credibility_score, 0.4) AS credibility
        FROM evidence e
        LEFT JOIN sources s ON s.domain = e.domain
        WHERE e.verdict_id = $1
        ORDER BY e.stance_score DESC
    """

    async with database.pool.acquire() as conn:
        rows = await conn.fetch(query, verdict_id)

    items = []
    for r in rows:
        domain = r["domain"] or ""
        credibility = r["credibility"]
        # Match the aggregation-time weight: sources.py special-cases every
        # Wikipedia edition to 0.75, which no seeded `sources` row represents —
        # the LEFT JOIN would otherwise re-read these as the 0.4 default.
        if domain.endswith("wikipedia.org"):
            from app.db.sources import WIKIPEDIA_CREDIBILITY
            credibility = WIKIPEDIA_CREDIBILITY

        items.append({
            "url": r["url"],
            "domain": domain,
            "title": r["title"],
            "snippet": r["snippet"],
            "stance": r["stance"],
            "stance_score": r["stance_score"],
            "published_at": r["published_at"].isoformat() if r["published_at"] else None,
            "credibility": credibility,
        })
    return items

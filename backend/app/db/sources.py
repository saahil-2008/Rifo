"""Sources table lookups + credibility resolution (PRD §9).

`sources` is seeded by db/migrations/003_seed_sources.sql with IFCN-signatory
fact-checkers, wire services, and national dailies. Unknown domains default to
0.4 in code; *.wikipedia.org is special-cased to 0.75 because the keyless
retrieval leg leans on Wikipedia as evidence (documented deviation — the user
has no Brave key, and 0.4 would under-weight every Wikipedia result).

Lookups are cached in-process; a failed DB read degrades to the default rather
than raising, so retrieval never breaks because the cache DB is down.
"""

from __future__ import annotations

import logging
from typing import Iterable

from app.db import database

logger = logging.getLogger(__name__)

DEFAULT_CREDIBILITY = 0.4
WIKIPEDIA_CREDIBILITY = 0.75

# In-process cache: domain -> credibility score
_cache: dict[str, float] = {}


def _wikipedia_credibility(domain: str) -> float | None:
    """Special-case any language edition of Wikipedia (en/hi/ta/bn/…)."""
    if domain.endswith("wikipedia.org"):
        return WIKIPEDIA_CREDIBILITY
    return None


async def _load_from_db(domain: str) -> float | None:
    """Read one row from the sources table. Returns None on miss or error."""
    if database.pool is None:
        return None
    query = "SELECT credibility_score FROM sources WHERE domain = $1"
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(query, domain)
    except Exception as e:
        logger.warning("sources: DB lookup failed for '%s': %s", domain, e)
        return None
    return row["credibility_score"] if row else None


async def get_credibility(domain: str) -> float:
    """Resolve the credibility score for a single evidence domain."""
    domain = (domain or "").strip().lower()
    if not domain:
        return DEFAULT_CREDIBILITY
    if domain in _cache:
        return _cache[domain]

    cred = _wikipedia_credibility(domain)
    if cred is None:
        cred = await _load_from_db(domain)
    if cred is None:
        cred = DEFAULT_CREDIBILITY

    _cache[domain] = cred
    return cred


async def get_credibility_map(domains: Iterable[str]) -> dict[str, float]:
    """Resolve credibility for many domains, deduplicated."""
    result: dict[str, float] = {}
    for domain in dict.fromkeys([d or "" for d in domains]):
        result[domain] = await get_credibility(domain)
    return result

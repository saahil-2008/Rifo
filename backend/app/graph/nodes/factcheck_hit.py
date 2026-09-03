"""Fact-check lookup node.

Queries the Google Fact Check Tools API (plus, implicitly, the ClaimReview
corpus behind it). On a decisive match it short-circuits — the graph skips
retrieve + nli_stance and goes straight to aggregate. This resolves most
celebrity death hoaxes in ~150 ms (PRD §FR-5).

Decision rule: we only short-circuit when at least one review maps to a
supports/refutes stance. A genuinely neutral match (e.g. "unverified") is not
decisive, so it falls through to web retrieval for more evidence.
"""

from __future__ import annotations

import logging

from app.config import settings
from app.models.state import PipelineState
from app.services.factcheck_api import search_claims
from app.db.sources import get_credibility_map

logger = logging.getLogger(__name__)


async def factcheck_hit(state: PipelineState) -> PipelineState:
    """Check Google Fact Check Tools for an existing fact-check."""
    claim = state.get("claim", "")
    claim_original = state.get("claim_original", "")
    source_lang = state.get("source_lang", "en")

    if not settings.google_factcheck_api_key:
        logger.info("factcheck_hit: no API key — continuing to retrieve")
        return {}

    # Search the normalized English claim always; also fork to the source
    # language when present, mirroring the retrieve node's multilingual split.
    queries = [(claim, "en")]
    if source_lang != "en" and claim_original:
        queries.append((claim_original, source_lang))

    results: list[dict] = []
    for query, lang in queries:
        try:
            results.extend(await search_claims(query, lang))
        except Exception as e:
            logger.warning("factcheck_hit: lookup failed for '%s' (%s): %s", query[:60], lang, e)

    # Deduplicate by URL, keeping the strongest stance.
    strong: list[dict] = []
    seen_urls: set[str] = set()
    for item in sorted(results, key=lambda i: 0 if i["stance"] == "neutral" else 1, reverse=True):
        url = item.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        strong.append(item)

    decisive = [i for i in strong if i["stance"] in ("supports", "refutes")]
    if not decisive:
        logger.info("factcheck_hit: no decisive review for '%s' — continuing to retrieve", claim[:60])
        return {}

    # Resolve real credibility scores from the seeded sources table.
    domains = [i.get("domain", "") for i in decisive]
    cred_map = await get_credibility_map(domains)
    for item in decisive:
        item["credibility"] = cred_map.get(item.get("domain", "").lower(), 0.4)

    logger.info("factcheck_hit: %d decisive reviews → short-circuit to aggregate", len(decisive))
    return {
        "evidence_items": decisive,
        "stances": decisive,
        "factcheck_hit": True,
    }

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

import asyncio
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
    # language when present in parallel.
    queries = [(claim, "en")]
    if source_lang != "en" and claim_original:
        queries.append((claim_original, source_lang))

    raw_results = await asyncio.gather(
        *(search_claims(query, lang) for query, lang in queries),
        return_exceptions=True,
    )
    results: list[dict] = []
    for res in raw_results:
        if isinstance(res, list):
            results.extend(res)

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

    from app.services.ml_models import embed_text

    def cos_sim(v1, v2):
        if not v1 or not v2: return 0.0
        dot = sum(a*b for a, b in zip(v1, v2))
        n1 = sum(a*a for a in v1)**0.5
        n2 = sum(b*b for b in v2)**0.5
        return dot / (n1 * n2) if n1 * n2 else 0.0

    claim_embedding = state.get("embedding", [])
    relevant_decisive = []

    for item in decisive:
        title = item.get("title", "")
        try:
            item_emb = embed_text(title)
            sim = cos_sim(claim_embedding, item_emb)
            if sim >= 0.90:
                relevant_decisive.append(item)
            else:
                logger.info("factcheck_hit: discarding irrelevant hit '%.60s' (sim=%.2f)", title, sim)
        except Exception as e:
            logger.warning("factcheck_hit: embedding failed for filter: %s", e)
            relevant_decisive.append(item)

    if not relevant_decisive:
        logger.info("factcheck_hit: no relevant decisive review for '%s' — continuing to retrieve", claim[:60])
        return {}

    # Resolve real credibility scores from the seeded sources table.
    domains = [i.get("domain", "") for i in relevant_decisive]
    cred_map = await get_credibility_map(domains)
    for item in relevant_decisive:
        item["credibility"] = cred_map.get(item.get("domain", "").lower(), 0.4)

    logger.info("factcheck_hit: %d decisive reviews → short-circuit to aggregate", len(relevant_decisive))
    return {
        "evidence_items": relevant_decisive,
        "stances": relevant_decisive,
        "factcheck_hit": True,
    }

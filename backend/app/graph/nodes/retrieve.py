"""Evidence retrieval node.

Runs Wikipedia article search, Wikipedia recent-articles search, and (when
has_image_content) reverse image search — all inside a single asyncio.gather
with return_exceptions=True and per-source timeouts (PRD §FR-5).

When source_lang != "en", forks the query: source-language Wikipedia edition +
English edition within the same gather, so regional debunks surface. Regional
snippets are translated to English before nli_stance when an LLM key exists.

NOTE (documented deviation): the PRD mandates Brave web + Brave news search.
The user has no Brave key, so this leg uses keyless Wikipedia instead. Items
are credibility-weighted via the seeded `sources` table with a Wikipedia
special-case. The broaden-on-retry behaviour is preserved.
"""

from __future__ import annotations

import asyncio
import logging

from app.models.state import PipelineState
from app.services.wikipedia_search import search_articles, search_recent
from app.services import translate

logger = logging.getLogger(__name__)

# Per-source timeout (seconds)
SOURCE_TIMEOUT = 3.0


async def _safe_search(coro, label: str) -> list[dict]:
    """Wrap a search coroutine with timeout and error handling."""
    try:
        return await asyncio.wait_for(coro, timeout=SOURCE_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("retrieve: %s timed out after %.1fs", label, SOURCE_TIMEOUT)
        return []
    except Exception as e:
        logger.warning("retrieve: %s failed: %s", label, e)
        return []


async def retrieve(state: PipelineState) -> PipelineState:
    """Retrieve evidence from multiple sources in parallel via asyncio.gather.

    Sources searched:
    1. Wikipedia article search (English)
    2. Wikipedia recent articles (English)
    3. When source_lang != "en": Wikipedia in the source language (fork)
    4. When has_image_content: reverse image search (inside same gather)
    """
    claim = state.get("claim", "")
    source_lang = state.get("source_lang", "en")
    has_image = state.get("has_image_content", False)
    retry_count = state.get("retry_count", 0)

    logger.info(
        "retrieve: fetching evidence for '%s' (lang=%s, has_image=%s, retry=%d)",
        claim[:60], source_lang, has_image, retry_count,
    )

    # Broaden query on retry (hard cap one retry — constraint #17)
    query = claim
    if retry_count > 0:
        query = f"{claim} fact check verify"
        logger.info("retrieve: broadened query for retry: '%s'", query[:80])

    # ── Build the gather tasks. Each job carries its language so retrieved
    #    items can be tagged for the optional pre-NLI translation pass. ──
    jobs: list[dict] = []

    def add_job(lang: str, coro) -> None:
        jobs.append({"lang": lang, "coro": _safe_search(coro, f"search_{lang}")})

    add_job("en", search_articles(query, count=3, lang="en"))
    add_job("en", search_recent(query, count=2, lang="en"))

    # Fork for source language (parallel, no additional latency)
    if source_lang != "en":
        claim_original = state.get("claim_original", claim)
        add_job(source_lang, search_articles(claim_original, count=3, lang=source_lang))
        add_job(source_lang, search_recent(claim_original, count=2, lang=source_lang))

    # Reverse image search runs inside the same gather (constraint #19), never
    # sequentially after NLI. Its result is collected into ris_out and surfaced
    # as state so aggregate can evaluate `manipulated`.
    ris_out: dict = {}
    if has_image:
        from app.graph.nodes.reverse_image import reverse_image_search as ris_node

        async def _run_ris() -> list[dict]:
            try:
                ris_out.update(await ris_node(state))
            except Exception as e:
                logger.warning("retrieve: reverse image leg failed: %s", e)
            return []

        add_job("en", _run_ris())

    # ── Execute all in parallel ──
    results = await asyncio.gather(
        *(job["coro"] for job in jobs),
        return_exceptions=True,
    )

    # ── Merge and deduplicate results, tagging non-English items ──
    all_evidence: list[dict] = []
    non_en_items: list[dict] = []
    seen_urls: set[str] = set()

    for job, result in zip(jobs, results):
        if isinstance(result, Exception) or not isinstance(result, list):
            logger.warning("retrieve: a source returned an exception: %s", result)
            continue
        lang = job["lang"]
        for item in result:
            url = item.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_evidence.append(item)
                if lang != "en":
                    non_en_items.append(item)

    logger.info("retrieve: collected %d unique evidence items", len(all_evidence))

    # ── Pre-NLI translation (PRD FR-5): dormant without an LLM key ──
    # Translated text goes into snippet_en so the original snippet remains for
    # display; nli_stance prefers snippet_en when present.
    if non_en_items and translate.llm_configured():
        logger.info("retrieve: translating %d non-English snippets before NLI", len(non_en_items))
        for item in non_en_items[:8]:
            snippet = item.get("snippet", "")
            if snippet:
                translated = await translate.translate_text(snippet)
                if translated and translated != snippet:
                    item["snippet_en"] = translated
    elif non_en_items:
        logger.info(
            "retrieve: %d non-English snippets left untranslated (no LLM key) — "
            "known limitation, NLI judges them in their source language",
            len(non_en_items),
        )

    out: dict = {"evidence_items": all_evidence}
    if ris_out.get("earliest_date") or ris_out.get("earliest_url"):
        out["earliest_url"] = ris_out.get("earliest_url", "")
        out["earliest_date"] = ris_out.get("earliest_date", "")
    return out

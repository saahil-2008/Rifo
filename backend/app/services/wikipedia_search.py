"""Wikipedia API client for evidence retrieval.

Uses the MediaWiki API (free, no key required) to search for
relevant articles and extract snippets as evidence.

Two functions mirror what Brave used to provide:
  - search_articles: general Wikipedia article search
  - search_news: searches Wikipedia's current events / recent articles

Endpoint: https://en.wikipedia.org/w/api.php
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"

# Timeout per request (used inside asyncio.gather with return_exceptions=True)
REQUEST_TIMEOUT = 3.0

# Wikipedia MediaWiki API policy requires a descriptive User-Agent
WIKIPEDIA_HEADERS = {
    "User-Agent": "RifoFactChecker/1.0 (https://rifo.app; dev@rifo.app)"
}

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=WIKIPEDIA_HEADERS)
    return _client


async def search_articles(
    query: str,
    count: int = 10,
    lang: str = "en",
) -> list[dict]:
    """Search Wikipedia for articles related to the query.

    Uses the MediaWiki opensearch + query APIs to find and extract
    relevant article snippets.

    Args:
        query: Search query string.
        count: Maximum number of results.
        lang: Wikipedia language edition (e.g. "en", "hi", "ta").

    Returns:
        List of evidence-shaped dicts with url, domain, title, snippet.
    """
    base_url = f"https://{lang}.wikipedia.org/w/api.php"

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": count,
        "srprop": "snippet|timestamp",
        "format": "json",
        "utf8": 1,
    }

    try:
        client = _get_client()
        resp = await client.get(base_url, params=params)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("query", {}).get("search", []):
            # Strip HTML tags from snippet
            snippet = item.get("snippet", "")
            snippet = snippet.replace('<span class="searchmatch">', "").replace("</span>", "")

            title = item.get("title", "")
            page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"

            results.append({
                "url": page_url,
                "domain": f"{lang}.wikipedia.org",
                "title": title,
                "snippet": snippet,
                "stance": "",  # populated by nli_stance
                "stance_score": 0.0,
                "published_at": item.get("timestamp", ""),
                "credibility": 0.75,  # Wikipedia is generally reliable
            })

        logger.info("wikipedia: found %d articles for '%s' (lang=%s)", len(results), query[:60], lang)

        # Resolve credibility from the seeded sources table (with a Wikipedia
        # special-case) so aggregation weights match the rest of the stack.
        if results:
            from app.db.sources import get_credibility
            cred = await get_credibility(results[0]["domain"])
            for r in results:
                r["credibility"] = cred

        return results

    except Exception as e:
        logger.warning("wikipedia: search failed for '%s': %s", query[:60], e)
        return []


async def search_recent(
    query: str,
    count: int = 5,
    lang: str = "en",
) -> list[dict]:
    """Search Wikipedia for recently modified articles related to the query.

    Useful for finding coverage of recent events. Uses the same API
    but sorts by last-edit recency.

    Args:
        query: Search query string.
        count: Maximum number of results.
        lang: Wikipedia language edition.

    Returns:
        List of evidence-shaped dicts.
    """
    base_url = f"https://{lang}.wikipedia.org/w/api.php"

    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": count,
        "srprop": "snippet|timestamp",
        "srsort": "last_edit_desc",
        "format": "json",
        "utf8": 1,
    }

    try:
        client = _get_client()
        resp = await client.get(base_url, params=params)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("query", {}).get("search", []):
            snippet = item.get("snippet", "")
            snippet = snippet.replace('<span class="searchmatch">', "").replace("</span>", "")

            title = item.get("title", "")
            page_url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"

            results.append({
                "url": page_url,
                "domain": f"{lang}.wikipedia.org",
                "title": title,
                "snippet": snippet,
                "stance": "",
                "stance_score": 0.0,
                "published_at": item.get("timestamp", ""),
                "credibility": 0.75,
            })

        logger.info("wikipedia: found %d recent articles for '%s' (lang=%s)", len(results), query[:60], lang)

        if results:
            from app.db.sources import get_credibility
            cred = await get_credibility(results[0]["domain"])
            for r in results:
                r["credibility"] = cred

        return results

    except Exception as e:
        logger.warning("wikipedia: recent search failed for '%s': %s", query[:60], e)
        return []

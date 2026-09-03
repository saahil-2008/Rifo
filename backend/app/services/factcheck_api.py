"""Google Fact Check Tools API client.

Queries the claims:search endpoint for existing ClaimReview entries and maps
each publisher's textual/numeric rating onto the pipeline's
supports/refutes/neutral stance vocabulary (with a strength score).

This is the ~150 ms short-circuit leg (PRD §FR-5): it resolves most celebrity
death hoaxes before any web retrieval happens. The only cost is one HTTP GET;
no key → the leg degrades gracefully to no results.

Ref: https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

FACTCHECK_API_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
REQUEST_TIMEOUT = 5.0
MAX_ITEMS = 8

# ── Rating text → stance (order matters: refute words checked first) ──
_REFUTE_WORDS = (
    "false", "fake", "fabricat", "hoax", "incorrect", "wrong", "debunk",
    "altered", "doctored", "manipulated", "photoshop", "not true", "untrue",
    "myth", "satir", "fraud", "misinform", "misinformation",
)
_SUPPORT_WORDS = (
    "true", "accurate", "correct", "genuine", "real", "supported",
    "confirmed", "authentic", "verified", "legitimate",
)
# Words that weaken a rating ("mostly false" is still refutes, but softer)
_WEAK_WORDS = ("mostly", "partly", "largely", "majority")


def map_rating_to_stance(
    textual_rating: str | None,
    rating_value: float | None = None,
    best_rating: float | None = None,
    worst_rating: float | None = None,
) -> tuple[str, float]:
    """Map a ClaimReview rating onto (stance, stance_score).

    Textual rating takes priority; the numeric rating is a fallback. Strong
    ratings score ~0.9, softened ratings (mostly/partly) score ~0.7, and
    genuinely ambiguous ratings map to a neutral 0.5 so the aggregate node
    keeps the decision.
    """
    text = (textual_rating or "").strip().lower()
    softened = any(w in text for w in _WEAK_WORDS)

    if text:
        if any(w in text for w in _REFUTE_WORDS):
            return "refutes", 0.7 if softened else 0.9
        if any(w in text for w in _SUPPORT_WORDS):
            return "supports", 0.7 if softened else 0.9

    # Numeric fallback: normalize ratingValue between worst and best.
    if (
        rating_value is not None
        and best_rating is not None
        and worst_rating is not None
        and best_rating > worst_rating
    ):
        ratio = (rating_value - worst_rating) / (best_rating - worst_rating)
        if ratio <= 0.45:
            return "refutes", round(0.5 + (0.45 - ratio), 2)
        if ratio >= 0.55:
            return "supports", round(0.5 + (ratio - 0.55), 2)
        return "neutral", 0.5

    return "neutral", 0.5


def _domain_of(site: str | None, url: str | None) -> str:
    """Best-effort domain from publisher.site, else from the review URL."""
    if site:
        return site.strip().lower().removeprefix("www.")
    try:
        host = urlparse(url or "").netloc.lower()
        return host.removeprefix("www.")
    except ValueError:
        return ""


async def search_claims(query: str, language_code: str = "en") -> list[dict]:
    """Query the Google Fact Check Tools API for existing fact-checks.

    Args:
        query: The normalized claim (English) or source-language wording.
        language_code: BCP-47 code for the results (e.g. "en", "hi").

    Returns:
        List of evidence-shaped dicts (url, domain, title, snippet, stance,
        stance_score, published_at). Empty list on no key, no match, or error
        — this leg must never raise into the pipeline.
    """
    if not settings.google_factcheck_api_key:
        logger.info("factcheck: no API key configured — skipping lookup")
        return []

    params = {
        "query": query,
        "languageCode": language_code,
        "key": settings.google_factcheck_api_key,
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(FACTCHECK_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("factcheck: lookup failed for '%s': %s", query[:60], e)
        return []

    claims = data.get("claims") or []
    logger.info("factcheck: %d claim reviews for '%s' (lang=%s)", len(claims), query[:60], language_code)

    items: list[dict] = []
    for claim in claims:
        reviews = claim.get("claimReview") or []
        if not reviews:
            continue
        # Prefer the review with the strongest (non-neutral) rating.
        reviews.sort(
            key=lambda rv: _stance_rank(map_rating_to_stance(
                (rv.get("reviewRating") or {}).get("alternateName")
                or rv.get("textualRating") or claim.get("textualRating"),
            )),
            reverse=True,
        )
        review = reviews[0]
        rating = review.get("reviewRating") or {}
        textual = (
            rating.get("alternateName")
            or rating.get("textualRating")
            or review.get("textualRating")
            or claim.get("textualRating")
        )
        stance, stance_score = map_rating_to_stance(
            textual,
            rating_value=_as_float(rating.get("ratingValue")),
            best_rating=_as_float(rating.get("bestRating")),
            worst_rating=_as_float(rating.get("worstRating")),
        )
        url = review.get("url") or ""
        domain = _domain_of((review.get("publisher") or {}).get("site"), url)

        items.append({
            "url": url,
            "domain": domain,
            "title": review.get("title") or claim.get("text") or query,
            "snippet": textual or (review.get("title") or "")[:200],
            "stance": stance,
            "stance_score": stance_score,
            "published_at": (review.get("reviewDate") or claim.get("reviewDate") or ""),
            "credibility": 0.4,  # node resolves real value from the sources table
        })

    return items[:MAX_ITEMS]


def _stance_rank(stance: tuple[str, float]) -> int:
    """Rank ratings so non-neutral reviews sort first when multiple exist."""
    return {"refutes": 2, "supports": 1, "neutral": 0}[stance[0]]


def _as_float(value) -> float | None:
    """Parse numeric JSON fields defensively."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

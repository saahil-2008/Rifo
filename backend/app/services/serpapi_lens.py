"""SerpApi Google Lens client for reverse image search.

Called ONLY when has_image_content is true, ONLY inside the retrieve
asyncio.gather (constraint #19). This is the only metered API in the stack, so
it must never be invoked speculatively and must degrade to no results when no
key is configured.

Output: the earliest publication date across visual matches, which the
aggregate node uses to reach the `manipulated` verdict.

Ref: https://serpapi.com/google-lens-api
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SERPAPI_URL = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 6.0

# Matches ISO-ish dates and "YYYY-MM-DD" prefixes inside free-form date strings.
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_date(text: str | None) -> datetime | None:
    """Best-effort parse of a SerpApi published_date string to a datetime."""
    if not text:
        return None
    try:
        cleaned = text.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    m = _ISO_DATE.search(text)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
            )
        except ValueError:
            return None
    return None


def _earliest_match(visual_matches: list[dict]) -> tuple[str, str]:
    """Return (earliest_url, earliest_date_iso) across visual matches."""
    earliest: datetime | None = None
    earliest_url = ""
    for match in visual_matches:
        dt = _parse_date(match.get("published_date"))
        if dt is None:
            continue
        if earliest is None or dt < earliest:
            earliest = dt
            earliest_url = match.get("link") or match.get("source") or ""
    return earliest_url, earliest.isoformat() if earliest else ""


async def reverse_image_search(image_b64: str) -> dict:
    """Reverse-image search via SerpApi Google Lens.

    Args:
        image_b64: Base64-encoded screenshot JPEG.

    Returns:
        dict with keys earliest_url, earliest_date (ISO), visual_matches.
        Empty dict (earliest fields "") when no key, no date found, or error.
    """
    if not settings.serpapi_key:
        logger.info("serpapi_lens: no API key configured — skipping reverse image search")
        return {}

    params = {
        "engine": "google_lens",
        "image_base64": image_b64,
        "api_key": settings.serpapi_key,
    }

    try:
        # POST keeps the (large) base64 payload out of the URL.
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(SERPAPI_URL, data=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("serpapi_lens: request failed: %s", e)
        return {}

    if "error" in data:
        logger.warning("serpapi_lens: API error: %s", data.get("error"))
        return {}

    visual_matches = data.get("visual_matches") or []
    earliest_url, earliest_date = _earliest_match(visual_matches)
    logger.info(
        "serpapi_lens: %d visual matches, earliest=%s",
        len(visual_matches),
        earliest_date or "n/a",
    )

    return {
        "earliest_url": earliest_url,
        "earliest_date": earliest_date,
        "visual_matches": visual_matches[:5],
    }

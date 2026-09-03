"""Optional snippet translation (PRD §FR-5).

Non-English evidence snippets must be judged in English by the NLI model, which
understands a fixed set of languages. This helper is ONLY active when an
Anthropic or OpenAI key is configured — in a no-LLM-key deployment it is a
pass-through, and the limitation is documented rather than silently wrong.

Translation happens into item["snippet_en"] (see retrieve node) so the original
snippet stays available for display, per PRD §FR-5 ("titles and snippets stay
in their original language").
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

TRANSLATE_PROMPT = (
    "Translate the following text into English. Return ONLY the translation, "
    "with no preamble, quotes, or explanation.\n\n{text}"
)


def llm_configured() -> bool:
    """True when an explanation LLM key is present (translation is possible)."""
    return bool(settings.anthropic_api_key or settings.openai_api_key)


async def translate_text(text: str) -> str:
    """Translate a single text to English. Identity when no key is set."""
    if not text or not llm_configured():
        return text

    prompt = TRANSLATE_PROMPT.format(text=text)
    try:
        if settings.anthropic_api_key:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
            response = await client.messages.create(
                model=settings.explanation_model,
                max_tokens=400,
                temperature=0.0,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()

        import openai
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.explanation_fallback_model,
            max_tokens=400,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("translate: failed (returning original): %s", e)
        return text

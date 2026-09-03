"""Localization node.

Translates the verdict label and explanation into the source language.
Evidence titles and snippets stay in their original language (PRD §FR-5).
No-op when source_lang == "en".

The five verdict labels are fixed, so they are localized with a deterministic
static map — fast, no API, no parsing. The explanation body is translated via
Claude/OpenAI only when a key is configured (the user currently has none), and
otherwise is streamed in English and logged as a documented limitation.
"""

from __future__ import annotations

import logging

from app.models.state import PipelineState
from app.config import settings
from app.services import translate

logger = logging.getLogger(__name__)

# Language names for LLM prompts / logging
LANG_NAMES = {
    "hi": "Hindi", "mr": "Marathi", "bn": "Bengali", "ta": "Tamil",
    "te": "Telugu", "kn": "Kannada", "ml": "Malayalam", "gu": "Gujarati",
    "pa": "Punjabi", "or": "Odia", "ur": "Urdu",
}

# ── Static translations of the five verdict labels (FR-6 taxonomy) ──
STATIC_LABELS: dict[str, dict[str, str]] = {
    "genuine": {
        "hi": "प्रामाणिक", "mr": "खरा", "bn": "প্রকৃত", "ta": "உண்மையான",
        "te": "నిజమైన", "kn": "ನಿಜವಾದ", "ml": "യഥാർത്ഥ", "gu": "સાચું",
        "pa": "ਅਸਲੀ", "or": "ପ୍ରକୃତ", "ur": "حقیقی",
    },
    "misleading": {
        "hi": "भ्रामक", "mr": "दिशाभूल करणारे", "bn": "বিভ্রান্তিকর", "ta": "தவறாக வழிநடத்தும்",
        "te": "తప్పుదారి పట్టించే", "kn": "ತಪ್ಪುದಾರಿಗೆಳೆಯುವ", "ml": "തെറ്റിദ്ധരിപ്പിക്കുന്ന",
        "gu": "ગેરમાર્ગે દોરનારું", "pa": "ਭੁਲੇਖਾ ਪਾਉਣ ਵਾਲਾ", "or": "ଭ୍ରାନ୍ତିକର", "ur": "گمراہ کن",
    },
    "fake": {
        "hi": "फर्जी", "mr": "बनावटी", "bn": "ভুয়া", "ta": "போலியான",
        "te": "నకిలీ", "kn": "ನಕಲಿ", "ml": "വ്യാജം", "gu": "નકલી",
        "pa": "ਫਰਜ਼ੀ", "or": "ନକଲି", "ur": "جعلی",
    },
    "manipulated": {
        "hi": "छेड़छाड़ वाला", "mr": "छेडछाड केलेले", "bn": "কারচুপিকৃত", "ta": "கையாளப்பட்ட",
        "te": "మార్చబడిన", "kn": "ಬದಲಾಯಿಸಲಾದ", "ml": "കൃത്രിമം ചെയ്ത", "gu": "છેડછાડ કરેલ",
        "pa": "ਹੇਰਾਫੇਰੀ ਕੀਤਾ", "or": "ଅଦଳବଦଳ କରାଯାଇଥିବା", "ur": "جوڑ توڑ کے ساتھ پیش کیا گیا",
    },
    "insufficient": {
        "hi": "अपर्याप्त सबूत", "mr": "अपुरे पुरावे", "bn": "অপর্যাপ্ত প্রমাণ", "ta": "போதிய ஆதாரம் இல்லை",
        "te": "సరిపోని ఆధారాలు", "kn": "ಸಾಕಷ್ಟು ಪುರಾವೆ ಇಲ್ಲ", "ml": "തെളിവ് പോരാ", "gu": "પૂરતા પુરાવા નથી",
        "pa": "ਨਾਕਾਫ਼ੀ ਸਬੂਤ", "or": "ଅପର୍ଯ୍ୟାପ୍ତ ପ୍ରମାଣ", "ur": "ناکافی ثبوت",
    },
}


def _static_label(label: str, lang: str) -> str | None:
    return STATIC_LABELS.get(label, {}).get(lang)


async def localize(state: PipelineState) -> PipelineState:
    """Localize the verdict label and explanation into the source language."""
    source_lang = state.get("source_lang", "en")
    label = state.get("label", "insufficient")
    explanation = state.get("explanation", "")

    if source_lang == "en":
        logger.info("localize: source_lang is 'en', no-op")
        return {
            "label_localized": label,
            "explanation_localized": explanation,
        }

    logger.info("localize: localizing to %s (%s)", LANG_NAMES.get(source_lang, source_lang), source_lang)

    # ── Label: always deterministic, from the static map ──
    label_localized = _static_label(label, source_lang) or label

    # ── Explanation: LLM translation only when a key is configured ──
    explanation_localized = explanation
    if explanation and translate.llm_configured():
        translated = await translate.translate_text(
            f"Verdict label: {label}\nExplanation: {explanation}"
        )
        if translated and translated != f"Verdict label: {label}\nExplanation: {explanation}":
            explanation_localized = translated
        logger.info("localize: explanation translated for %s", source_lang)
    else:
        logger.info(
            "localize: explanation left in English (no LLM key) — known limitation"
        )

    return {
        "label_localized": label_localized,
        "explanation_localized": explanation_localized,
    }

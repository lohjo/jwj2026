"""
pipeline/translator.py — SEA-LION translation (input→EN, EN→output lang).

All translation goes through SEA-LION Gemma 9B-IT via OpenAI-compatible API.
Gemini and Groq must NEVER translate.
"""

import asyncio
import logging

import httpx
from langdetect import detect, LangDetectException

from config import SEALION_API_BASE, SEALION_API_KEY, TRANSLATOR_MODEL

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = {"en", "zh", "ms", "ta", "id", "th", "vi", "tl"}

_LANG_MAP = {
    "en": "en",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "zh": "zh",
    "ms": "ms",
    "id": "id",
    "ta": "ta",
    "th": "th",
    "vi": "vi",
    "tl": "tl",
}

LANG_NAMES = {
    "en": "English",
    "zh": "Mandarin Chinese (Simplified)",
    "ms": "Malay",
    "ta": "Tamil",
    "id": "Indonesian",
    "th": "Thai",
    "vi": "Vietnamese",
    "tl": "Filipino",
}


def detect_language(text: str) -> str:
    """
    Detect the language of the given text.

    Returns ISO 639-1 code. Returns 'en' for short text (< 20 chars),
    Singlish, or on detection failure.
    """
    if not text or not isinstance(text, str) or len(text) < 20:
        return "en"

    try:
        raw = detect(text)
        # Normalise Singlish to English
        if raw in ("en-sg", "sg"):
            return "en"
        mapped = _LANG_MAP.get(raw)
        if mapped:
            return mapped
        prefix = raw.split("-")[0]
        if prefix in SUPPORTED_LANGUAGES:
            return prefix
        logger.info("Detected unsupported language '%s'; defaulting to English", raw)
        return "en"
    except LangDetectException:
        logger.warning("Language detection failed; defaulting to English")
        return "en"
    except Exception:
        return "en"


async def translate_to_english(
    text: str,
    source_lang: str,
    runner=None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """
    Translate non-English text to English before detection.

    CRITICAL: Preserve original phrasing — do NOT fix grammar or paraphrase.
    Return original text unchanged on failure (fail-safe).
    """
    if source_lang == "en" or not text:
        return text

    lang_name = LANG_NAMES.get(source_lang, source_lang)
    prompt = (
        f"You are a precise translator. Translate the following text from "
        f"{lang_name} to English.\n\n"
        "Rules:\n"
        "- Preserve ALL original phrasing, grammar errors, and vocabulary exactly. "
        "Do NOT improve or paraphrase. Literal translation only.\n"
        "- For Singlish input: translate to standard Singapore English.\n"
        "- Output the translation ONLY. No preamble, no explanation, no quotation marks.\n\n"
        f"Text to translate:\n{text}"
    )

    return await _call_sealion_translate(text, prompt)


async def translate_from_english(
    text: str,
    target_lang: str,
    runner=None,
    user_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """
    Translate English explanation back to user's language.

    Keep these terms in English regardless of target language:
        AI-generated, deepfake, GUARD, OCR, SEA-LION, confidence score
    Return English text unchanged on failure (fail-safe).
    """
    if target_lang == "en" or not text:
        return text

    lang_name = LANG_NAMES.get(target_lang, target_lang)
    prompt = (
        f"You are a precise translator. Translate the following text from "
        f"English to {lang_name}.\n\n"
        "Rules:\n"
        "- Translate naturally and fluently.\n"
        "- Keep these words in English: AI-generated, deepfake, GUARD, OCR, "
        "SEA-LION, confidence score.\n"
        "- Output the translation ONLY. No preamble, no explanation, no quotation marks.\n\n"
        f"Text to translate:\n{text}"
    )

    return await _call_sealion_translate(text, prompt)


async def _call_sealion_translate(original_text: str, prompt: str) -> str:
    """Call SEA-LION Gemma model for translation via OpenAI-compatible API."""
    if not SEALION_API_KEY:
        logger.error("[Translate] OPENAI_API_KEY not set")
        return original_text

    url = f"{SEALION_API_BASE.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {SEALION_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TRANSLATOR_MODEL,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()
            return result if result else original_text
    except Exception as e:
        logger.warning("SEA-LION translation failed: %s; returning original text", e)
        return original_text

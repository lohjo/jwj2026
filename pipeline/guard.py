"""
pipeline/guard.py — SEA-LION GUARD safety classification.

Calls the SEA-LION GUARD model to classify content as safe or unsafe.
"""

import asyncio
import logging

import httpx

from config import SEALION_API_BASE, SEALION_API_KEY, GUARD_MODEL

logger = logging.getLogger(__name__)

# Shared async HTTP client
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


async def run_guard_detection(
    content: str,
    content_type: str = "text",
    source_lang: str = "en",
    timeout: float = 25.0,
) -> dict:
    """
    Run SEA-LION GUARD to classify content as safe or unsafe.

    Args:
        content: The text content to analyse (should be in English).
        content_type: One of 'text', 'image_caption', 'audio_transcript', 'video_transcript'.
        source_lang: ISO 639-1 code of the original source language.
        timeout: Request timeout in seconds.

    Returns:
        Dict with: is_safe (bool|None), label (str),
                   raw_response (dict), safety_flag (str|None).
    """
    _error_result = {
        "is_safe": None,
        "label": "api_error",
        "raw_response": {},
        "safety_flag": None,
    }

    if not content or not isinstance(content, str):
        return {**_error_result, "label": "invalid_input"}

    if not SEALION_API_KEY:
        return {**_error_result, "label": "api_key_missing"}

    content = content[:2000].strip()

    if source_lang != "en":
        logger.warning("[GUARD] Received non-English input: %s", source_lang)

    headers = {
        "Authorization": f"Bearer {SEALION_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GUARD_MODEL,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 256,
    }

    client = _get_http_client()

    # Call SEA-LION GUARD for safety classification
    try:
        resp = await asyncio.wait_for(
            client.post(
                f"{SEALION_API_BASE.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
            ),
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["choices"][0]["message"]["content"].strip()
        logger.info("[GUARD] Response: %s", raw_text[:200])

        # Parse label from response
        label = raw_text
        for line in raw_text.splitlines():
            lu = line.upper().strip()
            if lu.startswith("LABEL:"):
                label = line.split(":", 1)[1].strip()

        # Detect safety flags
        low = raw_text.lower()
        if "unsafe" in low:
            safety_flag = "unsafe"
            is_safe = False
        else:
            safety_flag = None
            is_safe = True

        return {
            "is_safe": is_safe,
            "label": label,
            "raw_response": data,
            "safety_flag": safety_flag,
        }

    except asyncio.TimeoutError:
        logger.warning("[GUARD] Request timed out")
        return {**_error_result, "label": "timeout"}
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            logger.error("[GUARD] Unauthorized (401). Check OPENAI_API_KEY for SEA-LION.")
            return {**_error_result, "label": "auth_error"}
        if status == 403:
            logger.error("[GUARD] Forbidden (403). Key may lack model permissions.")
            return {**_error_result, "label": "permission_denied"}
        if status == 429:
            logger.warning("[GUARD] Rate limited (429).")
            return {**_error_result, "label": "rate_limited"}
        if status is not None and status >= 500:
            logger.warning("[GUARD] Upstream server error (%s)", status)
            return {**_error_result, "label": "api_error"}
        logger.warning("[GUARD] HTTP error (%s)", status)
        return {**_error_result, "label": "api_error"}
    except httpx.RequestError as e:
        logger.warning("[GUARD] Network error: %s", e)
        return {**_error_result, "label": "network_error"}
    except Exception as e:
        logger.exception("[GUARD] Detection failed: %s", e)
        return _error_result

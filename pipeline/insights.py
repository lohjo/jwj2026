"""
pipeline/insights.py — Unified LLM call with Gemini API→Vertex AI fallback.

All LLM calls in the project MUST go through call_llm().
"""

import asyncio
import logging

from google import genai

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
)

logger = logging.getLogger(__name__)


def _classify_gemini_error(err: Exception) -> str:
    message = str(err).lower()
    if "api_key_invalid" in message or "api key not valid" in message:
        return "api_key_invalid"
    if "permission" in message or "403" in message:
        return "permission_denied"
    if "quota" in message or "rate" in message or "429" in message:
        return "quota_or_rate_limit"
    if "model" in message and ("not found" in message or "unsupported" in message):
        return "model_not_found"
    return "unknown"


async def call_llm(prompt: str, max_tokens: int = 1024) -> tuple[str, str]:
    """
    Call Gemini via API key. If it fails for ANY reason, fall back to Vertex AI.

    Never raises — returns empty string on total failure.

    Args:
        prompt: Full prompt string to send.
        max_tokens: Max output tokens.

    Returns:
        Tuple of (response_text, llm_used) where llm_used is
        "gemini" | "vertex" | "failed".
    """
    # ── Primary: Gemini ─────────────────────────────────────────────────
    try:
        if not GEMINI_API_KEY or GEMINI_API_KEY.lower().startswith("your_"):
            raise ValueError("GEMINI_API_KEY missing or placeholder")
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config={"max_output_tokens": max_tokens},
        )
        text = response.text.strip()
        if text:
            logger.debug("[LLM] Gemini OK")
            return text, "gemini"
        raise ValueError("Empty Gemini response")

    except Exception as gemini_err:
        reason = _classify_gemini_error(gemini_err)
        logger.warning(
            "[LLM] Gemini failed (reason=%s, error=%s), falling back to Vertex AI",
            reason,
            gemini_err,
        )

    # ── Fallback: Vertex AI ─────────────────────────────────────────────
    if not GOOGLE_CLOUD_PROJECT:
        logger.error("[LLM] GOOGLE_CLOUD_PROJECT not set — cannot fall back to Vertex AI")
        return "", "failed"

    try:
        client = genai.Client(
            vertexai=True,
            project=GOOGLE_CLOUD_PROJECT,
            location=GOOGLE_CLOUD_LOCATION,
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config={"max_output_tokens": max_tokens},
        )
        text = response.text.strip()
        if text:
            logger.info("[LLM] Vertex AI fallback OK")
            return text, "vertex"
        raise ValueError("Empty Vertex AI response")

    except Exception as vertex_err:
        logger.error(
            "[LLM] Both Gemini and Vertex AI failed. Vertex error: %s", vertex_err
        )
        return "", "failed"


async def run_insights(
    content: str,
    detection_result: dict,
    misinformation_result: dict | None = None,
    manipulation_result: dict | None = None,
) -> dict:
    """
    Generate plain-language explanation combining all detection results.

    Args:
        content: English-normalised content text.
        detection_result: Output from run_guard_detection().
        misinformation_result: Output from detect_misinformation() — optional.
        manipulation_result: Output from detect_image_manipulation() — optional.

    Returns:
        Dict with: explanation (str), is_harmful (bool), llm_used (str).
    """
    if not content or not isinstance(content, str):
        return {"explanation": "", "is_harmful": False, "llm_used": "failed"}

    # Build context sections
    guard_label = detection_result.get("label", "unknown")
    guard_context = ""
    _error_labels = (
        "api_error", "timeout", "api_key_missing",
        "auth_error", "permission_denied", "rate_limited", "network_error",
    )
    if guard_label not in _error_labels:
        guard_verdict = (
            "Unsafe"
            if detection_result.get("is_safe") is False
            else (
                "Safe"
                if detection_result.get("is_safe") is True
                else "Inconclusive"
            )
        )
        guard_context = (
            f"SEA-LION GUARD verdict: {guard_verdict} ({guard_label[:150]})\n"
        )

    misinfo_context = ""
    if misinformation_result and misinformation_result.get("misinformation_detected"):
        claims = "\n".join(
            f"- {c}" for c in misinformation_result.get("claims", [])
        )
        misinfo_context = (
            f"Misinformation detected — type: "
            f"{misinformation_result.get('misinformation_type')}\n"
            f"Suspicious claims:\n{claims or 'See explanation'}\n"
        )

    manip_context = ""
    if manipulation_result and manipulation_result.get("manipulation_detected"):
        signals = "\n".join(
            f"- {s}" for s in manipulation_result.get("signals", [])
        )
        manip_context = (
            f"Image manipulation detected — type: "
            f"{manipulation_result.get('manipulation_type')}\n"
            f"Visual signals:\n{signals or 'See explanation'}\n"
        )

    insights_prompt = f"""You are an AI content analyst writing a plain-language report for a general user in Singapore.

Content analysed:
{content[:800]}

Detection results:
{guard_context}{misinfo_context}{manip_context}

Write 2-3 sentences that:
1. State clearly what was found (or not found)
2. Explain the key reasons or signals for the verdict
3. Give one practical recommendation for the user

Rules:
- Plain text only — no bullet points, headers, or markdown
- Be factual and avoid alarmist language
- If evidence is weak or results are inconclusive, say so honestly
- If all checks returned no issues, clearly say the content appears genuine
"""

    HARMFUL_KEYWORDS = [
        "misinformation",
        "disinformation",
        "harmful",
        "dangerous",
        "incite",
        "violence",
        "hate",
        "scam",
        "fraud",
        "fake news",
        "manipulated",
        "fabricated",
        "deepfake",
    ]

    text, llm_used = await call_llm(insights_prompt, max_tokens=512)

    if not text:
        return {
            "explanation": "Analysis unavailable.",
            "is_harmful": False,
            "llm_used": llm_used,
        }

    is_harmful = any(kw in text.lower() for kw in HARMFUL_KEYWORDS)
    return {
        "explanation": text,
        "is_harmful": is_harmful,
        "llm_used": llm_used,
    }

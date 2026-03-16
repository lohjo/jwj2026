"""
pipeline/detector.py — Orchestrates guard + misinformation + manipulation detection.

This is the single entrypoint for the full detection pipeline.
"""

import asyncio
import json
import logging
import re

from pipeline.guard import run_guard_detection
from pipeline.insights import call_llm, run_insights

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


async def detect_misinformation(
    content: str, context_description: str = ""
) -> dict:
    """
    Detect AI-assisted misinformation in text content using call_llm().

    Args:
        content: English text to analyse.
        context_description: Optional context (e.g. "image caption").

    Returns:
        Dict with: misinformation_detected (bool), misinformation_type (str),
                   claims (list), explanation (str).
    """
    _fallback = {
        "misinformation_detected": False,
        "misinformation_type": "none",
        "claims": [],
        "explanation": "Unavailable.",
    }

    if not content or not isinstance(content, str):
        return _fallback

    source_context = (
        f"Source context: {context_description}\n" if context_description else ""
    )

    prompt = f"""You are a fact-checking assistant specialised in detecting AI-assisted misinformation.

{source_context}Content to analyse:
{content[:2000]}

Analyse for misinformation. Respond in JSON format only — no markdown, no preamble:

{{
  "misinformation_detected": true or false,
  "misinformation_type": "none | fabricated_quote | false_statistic | misleading_context | deepfake_narrative | coordinated_narrative | unknown",
  "claims": ["list of specific suspicious claims, empty array if none"],
  "explanation": "one paragraph plain-language explanation"
}}

Rules:
- Only flag where there is clear evidence of manipulation or false claims
- Do NOT flag opinions, clearly marked satire, or uncertain interpretations
- If content is too short or generic to assess, set misinformation_detected to false
- Base assessment only on the content provided, not assumptions"""

    try:
        raw, _llm_used = await call_llm(prompt, max_tokens=512)
        if raw:
            clean = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE
            ).strip()
            try:
                return json.loads(clean)
            except json.JSONDecodeError:
                # Try to extract the outermost JSON object from response
                brace_depth = 0
                start_idx = -1
                for i, ch in enumerate(clean):
                    if ch == '{':
                        if brace_depth == 0:
                            start_idx = i
                        brace_depth += 1
                    elif ch == '}':
                        brace_depth -= 1
                        if brace_depth == 0 and start_idx >= 0:
                            try:
                                return json.loads(clean[start_idx:i + 1])
                            except json.JSONDecodeError:
                                start_idx = -1
                # Parse what we can from the raw text
                detected = bool(re.search(r'"misinformation_detected"\s*:\s*true', clean, re.I))
                mtype_m = re.search(r'"misinformation_type"\s*:\s*"([^"]*)"', clean)
                expl_m = re.search(r'"explanation"\s*:\s*"((?:[^"\\]|\\.)*)', clean)
                return {
                    "misinformation_detected": detected,
                    "misinformation_type": mtype_m.group(1) if mtype_m else "unknown",
                    "claims": [],
                    "explanation": expl_m.group(1) if expl_m else clean[:300],
                }
    except Exception as e:
        logger.exception("[Misinformation] Detection failed: %s", e)

    return _fallback


async def run_full_detection(
    english_text: str,
    content_type: str = "text",
    source_lang: str = "en",
    image_path: str | None = None,
) -> dict:
    """
    Run the full detection pipeline: GUARD + misinformation (+ image manipulation).

    Args:
        english_text: English-normalised text to analyse.
        content_type: One of 'text', 'image', 'audio', 'video'.
        source_lang: ISO 639-1 code of original input language.
        image_path: Path to image file (for image manipulation detection).

    Returns:
        Dict with: detection_result, misinfo_result, manipulation_result,
                   insights_result.
    """
    # Run GUARD + misinformation concurrently
    coros = [
        run_guard_detection(english_text, content_type=content_type, source_lang=source_lang),
        detect_misinformation(english_text, context_description=content_type),
    ]

    gathered = await asyncio.gather(*coros, return_exceptions=True)

    detection_result = (
        gathered[0]
        if not isinstance(gathered[0], BaseException)
        else {
            "is_safe": None,
            "label": "api_error",
            "raw_response": {},
            "safety_flag": None,
        }
    )

    misinfo_result = (
        gathered[1]
        if not isinstance(gathered[1], BaseException)
        else {
            "misinformation_detected": False,
            "misinformation_type": "none",
            "claims": [],
            "explanation": "Unavailable.",
        }
    )

    # Image manipulation detection (if applicable)
    manipulation_result = None
    if image_path:
        try:
            from media.image import detect_image_manipulation

            manipulation_result = await detect_image_manipulation(image_path)
        except Exception as e:
            logger.exception("[Detector] Image manipulation detection failed: %s", e)
            manipulation_result = {
                "manipulation_detected": False,
                "manipulation_type": "unknown",
                "signals": [],
                "explanation": "Unavailable.",
            }

    # Run insights
    insights_result = await run_insights(
        english_text,
        detection_result,
        misinformation_result=misinfo_result,
        manipulation_result=manipulation_result,
    )

    # Combined is_safe: False if ANY flag is triggered; True if all pass; None on errors
    guard_safe = detection_result.get("is_safe")
    misinfo_detected = misinfo_result.get("misinformation_detected", False)
    is_harmful = (insights_result or {}).get("is_harmful", False)

    if guard_safe is None:
        combined_is_safe = None
    elif guard_safe is False or misinfo_detected or is_harmful:
        combined_is_safe = False
    else:
        combined_is_safe = True

    misinfo_type = misinfo_result.get("misinformation_type", "none")

    return {
        "detection_result": detection_result,
        "misinfo_result": misinfo_result,
        "manipulation_result": manipulation_result,
        "insights_result": insights_result,
        "is_safe": combined_is_safe,
        "misinfo_type": misinfo_type,
    }

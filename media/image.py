"""
media/image.py — Image download, OCR, and manipulation detection.
"""

import asyncio
import logging
import os

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


async def extract_text_from_image(image_path: str) -> dict:
    """
    Extract text from an image using Gemini Vision OCR, with Tesseract fallback.

    Args:
        image_path: Path to the image file on disk.

    Returns:
        dict: text (str), confidence (float), method (str), error (str|None).
    """
    # Try Gemini Vision OCR first
    if GEMINI_API_KEY:
        try:
            from google import genai
            from google.genai import types as genai_types
            from PIL import Image

            prompt = (
                "Extract ALL visible text from this image exactly as written. "
                "Preserve line breaks and formatting. "
                "If no text is visible, respond with exactly: NO_TEXT_DETECTED"
            )

            def _call():
                client = genai.Client(api_key=GEMINI_API_KEY)
                img = Image.open(image_path)
                resp = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[prompt, img],
                )
                return resp.text if hasattr(resp, "text") else str(resp)

            raw = await asyncio.to_thread(_call)
            if raw:
                raw = raw.strip()
                if raw == "NO_TEXT_DETECTED":
                    return {"text": "", "confidence": 0.9, "method": "gemini_vision", "error": None}
                return {"text": raw, "confidence": 0.9, "method": "gemini_vision", "error": None}
        except Exception as e:
            logger.warning("[OCR] Gemini Vision OCR failed: %s, trying Tesseract", e)

    # Fallback: Tesseract OCR
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        text = await asyncio.to_thread(pytesseract.image_to_string, img)
        text = (text or "").strip()
        return {"text": text, "confidence": 0.7, "method": "tesseract", "error": None}
    except ImportError:
        logger.warning("[OCR] pytesseract not installed; OCR unavailable")
        return {"text": "", "confidence": 0.0, "method": "none", "error": "No OCR provider available"}
    except Exception as e:
        logger.exception("[OCR] Tesseract OCR failed: %s", e)
        return {"text": "", "confidence": 0.0, "method": "none", "error": str(e)}


async def analyse_image_with_gemini(image_path: str) -> dict:
    """
    Use Gemini to analyse an image for AI-generation signals + OCR.

    Returns:
        dict: caption (str), ocr_text (str|None), ai_signals (str), raw_response (str).
    """
    if not GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY not set", "caption": "", "ocr_text": None, "ai_signals": ""}

    try:
        from google import genai
        from PIL import Image

        img = Image.open(image_path)
        prompt = """Analyse this image in detail:

1. **Description**: Describe what is shown in the image (1-2 sentences).
2. **Text extraction**: If there is any visible text in the image, extract it exactly as written.
   If no text, write "No text detected".
3. **AI-generation signals**: Look for signs that this image may be AI-generated:
   - Unnatural textures, lighting, or shadows
   - Warped or inconsistent geometry (extra fingers, asymmetric features)
   - Repeating patterns, tiling artifacts
   - Overly smooth skin or surfaces
   - Inconsistent reflections or perspective

Respond in this exact format:
DESCRIPTION: <your description>
OCR_TEXT: <extracted text or "No text detected">
AI_SIGNALS: <your analysis>"""

        def _call():
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[prompt, img],
            )
            return resp.text if hasattr(resp, "text") else str(resp)

        text = await asyncio.to_thread(_call)

        caption = ""
        ocr_text = None
        ai_signals = ""

        for line in text.split("\n"):
            if line.startswith("DESCRIPTION:"):
                caption = line.replace("DESCRIPTION:", "").strip()
            elif line.startswith("OCR_TEXT:"):
                raw = line.replace("OCR_TEXT:", "").strip()
                ocr_text = None if raw.lower() == "no text detected" else raw
            elif line.startswith("AI_SIGNALS:"):
                ai_signals = line.replace("AI_SIGNALS:", "").strip()

        return {
            "caption": caption or text[:200],
            "ocr_text": ocr_text,
            "ai_signals": ai_signals,
            "raw_response": text,
        }
    except Exception as e:
        logger.exception("[Image] Gemini analysis failed: %s", e)
        return {"error": str(e), "caption": "", "ocr_text": None, "ai_signals": ""}


async def detect_image_manipulation(image_path: str) -> dict:
    """
    Detect signs of image manipulation using visual heuristics.

    Returns:
        dict: manipulation_detected (bool), manipulation_type (str),
              signals (list), explanation (str), confidence (float).
    """
    _fallback = {
        "manipulation_detected": False,
        "manipulation_type": "unknown",
        "signals": [],
        "explanation": "Unavailable.",
        "confidence": 0.0,
    }

    signals = []

    try:
        import cv2
        import numpy as np

        frame = await asyncio.to_thread(cv2.imread, image_path)
        if frame is None:
            return _fallback

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        if lap_var < 50:
            signals.append("Very smooth/shallow detail (low Laplacian variance)")

        # Edge density check
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = np.count_nonzero(edges) / edges.size
        if edge_ratio < 0.02:
            signals.append("Unusually low edge density")

        detected = len(signals) > 0
        confidence = min(0.3 + 0.2 * len(signals), 0.9)

        return {
            "manipulation_detected": detected,
            "manipulation_type": "visual_anomaly" if detected else "none",
            "signals": signals,
            "explanation": "; ".join(signals) if signals else "No manipulation detected.",
            "confidence": confidence if detected else 0.1,
        }
    except ImportError:
        logger.warning("[Image] OpenCV not available for manipulation detection")
        return _fallback
    except Exception as e:
        logger.exception("[Image] Manipulation detection failed: %s", e)
        return _fallback

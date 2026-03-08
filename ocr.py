"""OCR text extraction from images and video frame analysis."""

import os
import logging
import asyncio
from typing import Dict, Any, List, Union

from config import GEMINI_API_KEY, MODEL_NAME, extract_frames


async def extract_text_from_image(image_path: str) -> Dict[str, Any]:
    """
    Extract text from an image using Gemini Vision OCR, with Tesseract as fallback.

    Args:
        image_path: Path to the image file on disk.

    Returns:
        dict: text (str), confidence (float), method (str), error (str|None)
    """
    # Try Gemini Vision OCR first
    gemini_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            import google.genai as genai
            from PIL import Image

            os.environ.setdefault("GEMINI_API_KEY", gemini_key)
            os.environ.setdefault("GENAI_API_KEY", gemini_key)
            model_name = os.environ.get("MODEL_NAME", MODEL_NAME or "gemini-2.5-flash")

            prompt = (
                "Extract ALL visible text from this image exactly as written. "
                "Preserve line breaks and formatting. If no text is visible, respond with exactly: NO_TEXT_DETECTED"
            )

            def _call():
                Model = getattr(genai, "GenerativeModel", None)
                if Model is None:
                    return None
                try:
                    m = Model(model_name)
                except TypeError:
                    m = Model(model_name)
                img = Image.open(image_path)
                if hasattr(m, "generate_content"):
                    resp = m.generate_content([prompt, img])
                    return getattr(resp, "text", str(resp))
                return None

            raw = await asyncio.to_thread(_call)
            if raw:
                raw = raw.strip()
                if raw == "NO_TEXT_DETECTED":
                    return {"text": "", "confidence": 0.9, "method": "gemini_vision", "error": None}
                return {"text": raw, "confidence": 0.9, "method": "gemini_vision", "error": None}
        except Exception as e:
            logging.warning(f"[OCR] Gemini Vision OCR failed: {e}, trying Tesseract fallback")

    # Fallback: Tesseract OCR
    try:
        import pytesseract
        from PIL import Image

        img = Image.open(image_path)
        text = await asyncio.to_thread(pytesseract.image_to_string, img)
        text = (text or "").strip()
        return {"text": text, "confidence": 0.7, "method": "tesseract", "error": None}
    except ImportError:
        logging.warning("[OCR] pytesseract not installed; OCR unavailable")
        return {"text": "", "confidence": 0.0, "method": "none", "error": "No OCR provider available"}
    except Exception as e:
        logging.exception(f"[OCR] Tesseract OCR failed: {e}")
        return {"text": "", "confidence": 0.0, "method": "none", "error": str(e)}


async def analyse_video_frames(video_path: str, sample_every_seconds: float = 2.0) -> Dict[str, Any]:
    """
    Analyse video by sampling frames and running OCR + AI signal analysis.

    Uses config.extract_frames to sample frames, then runs detect_fake_image
    from image_detector on each frame.

    Args:
        video_path: Path to the video file.
        sample_every_seconds: Seconds between sampled frames.

    Returns:
        dict: frames_checked (int), frame_results (list), ocr_texts (list),
              aggregated_signals (list), fake_probability (float)
    """
    from image_detector import detect_fake_image

    results: Dict[str, Any] = {
        "frames_checked": 0,
        "frame_results": [],
        "ocr_texts": [],
        "aggregated_signals": [],
        "fake_probability": 0.0,
    }

    try:
        frames = await asyncio.to_thread(extract_frames, video_path)
    except Exception as e:
        logging.exception(f"[VideoFrames] Frame extraction failed: {e}")
        return {**results, "error": str(e)}

    if not frames:
        return {**results, "error": "No frames extracted from video"}

    suspicious = 0
    for frame_path in frames:
        try:
            info = await detect_fake_image(frame_path)
            results["frames_checked"] += 1
            results["frame_results"].append(info)

            if info.get("ai_signals"):
                results["aggregated_signals"].append(info["ai_signals"])
            if info.get("ocr_text"):
                results["ocr_texts"].append(info["ocr_text"])

            # Check for suspicious indicators
            raw = info.get("raw_response") or {}
            edge_score = raw.get("edge_score", 0) if isinstance(raw, dict) else 0
            if edge_score > 25:
                suspicious += 1
        except Exception as e:
            logging.warning(f"[VideoFrames] Failed to analyse frame {frame_path}: {e}")
        finally:
            try:
                if os.path.exists(frame_path):
                    os.remove(frame_path)
            except Exception:
                pass

    total = results["frames_checked"]
    results["fake_probability"] = suspicious / total if total > 0 else 0.0

    if not results["aggregated_signals"]:
        results["aggregated_signals"] = ["No strong signals detected across frames"]

    return results

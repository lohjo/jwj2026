import os
import re
import json
import asyncio
import logging
from config import GEMINI_API_KEY, MODEL_NAME
try:
    from ai_agent_adk.tools import escape_for_telegram
except Exception:
    def escape_for_telegram(s: str) -> str:
        return s


def detect_fake_text(text: str) -> str:
    prompt = f"""
Analyze the following WhatsApp or Telegram message.

Determine:
- Is it misinformation?
- Does it look like a scam/hoax?
- Give fake probability (0-100%).

Message:
{text}
"""

    try:
        import google.genai as genai
    except ImportError as e:
        return f"Gemini provider not available: {e}"

    gemini_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return "GEMINI_API_KEY not set in environment"

    def _extract_text(resp) -> str:
        """Extracts generated text from a Gemini API response."""
        if not resp:
            return ""
        # The primary way to get text from the new API is via `resp.text`
        if hasattr(resp, 'text') and isinstance(resp.text, str):
            return resp.text.strip()
        
        # Fallback for unexpected response structures
        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts") and candidate.content.parts:
                part = candidate.content.parts[0]
                # some SDKs put text under `text` or `content`
                if hasattr(part, 'text'):
                    return part.text.strip()
                if hasattr(part, 'content'):
                    return str(part.content).strip()
        
        return f"Could not extract text from response: {resp}"

    try:
        # Try to be compatible with multiple google-genai SDK variants.
        # Provide the key via common env vars so some SDKs pick it up automatically.
        os.environ.setdefault("GEMINI_API_KEY", gemini_key)
        os.environ.setdefault("GENAI_API_KEY", gemini_key)
        os.environ.setdefault("GOOGLE_API_KEY", gemini_key)

        # If the SDK exposes a configure() helper, prefer to call it.
        try:
            if hasattr(genai, "configure") and callable(getattr(genai, "configure")):
                try:
                    genai.configure(api_key=gemini_key)
                except TypeError:
                    # Some variants accept no args and read env vars; ignore if signature differs
                    genai.configure()
        except Exception:
            # Non-fatal: continue to other instantiation strategies
            pass

        model_name = os.environ.get("MODEL_NAME", MODEL_NAME or "gemini-2.5-flash")

        # Try several ways to invoke generation depending on SDK surface
        generation_exceptions = []

        # 1) Preferred: instantiate GenerativeModel and call generate_content / generate
        ModelCls = getattr(genai, "GenerativeModel", None)
        if ModelCls is not None:
            try:
                # Some constructors accept api_key kwarg, others rely on configure/env
                try:
                    model = ModelCls(model_name, api_key=gemini_key)
                except TypeError:
                    model = ModelCls(model_name)

                if hasattr(model, "generate_content"):
                    try:
                        resp = model.generate_content(prompt)
                    except TypeError:
                        resp = model.generate_content([prompt])
                    out = _extract_text(resp)
                    try:
                        return escape_for_telegram(out)
                    except Exception:
                        return out

                if hasattr(model, "generate"):
                    try:
                        resp = model.generate(prompt)
                    except TypeError:
                        resp = model.generate([prompt])
                    return _extract_text(resp)
            except Exception as e:
                generation_exceptions.append(e)

        # 2) Older or alternative SDK: top-level helper functions
        try:
            if hasattr(genai, "generate_text"):
                try:
                    resp = genai.generate_text(model=model_name, prompt=prompt)
                except TypeError:
                    resp = genai.generate_text(prompt)
                out = _extract_text(resp)
                try:
                    return escape_for_telegram(out)
                except Exception:
                    return out
        except Exception as e:
            generation_exceptions.append(e)

        # 3) Some SDKs expose a Client/Client-like API
        ClientCls = getattr(genai, "Client", None)
        if ClientCls is not None:
            try:
                try:
                    client = ClientCls(api_key=gemini_key)
                except TypeError:
                    client = ClientCls()
                if hasattr(client, "generate"):
                    resp = client.generate(model=model_name, prompt=prompt)
                    out = _extract_text(resp)
                    try:
                        return escape_for_telegram(out)
                    except Exception:
                        return out
            except Exception as e:
                generation_exceptions.append(e)

        # If we reach here, none of the strategies worked; fall back to a rule-based detector
        # and return a helpful analysis rather than failing completely.
        def rule_based_fallback(text: str) -> str:
            import re

            s = text.strip()
            low = s.lower()
            length = len(s)
            tokens = re.findall(r"\w+", s)
            token_count = max(1, len(tokens))
            digit_chars = sum(c.isdigit() for c in s)
            digit_ratio = digit_chars / max(1, length)
            currency_symbols = sum(s.count(c) for c in "$£€₹¥¢")
            urls = len(re.findall(r"https?://|www\.|\.com\b", low))
            promo_phrases = sum(1 for p in ["cost", "price", "per million", "fast mode", "fastmode", "pricing", "subscribe", "buy now", "token"] if p in low)
            named_entities = sum(1 for name in ["boris", "donald", "trump", "elon", "sundar"] if name in low)

            score = 0.3
            if digit_ratio > 0.02:
                score += 0.2
            if currency_symbols or promo_phrases:
                score += 0.25
            if urls:
                score += 0.15
            if named_entities:
                score += 0.05
            if length > 300:
                score += 0.05

            score = max(0.0, min(0.99, score))
            pct = int(score * 100)

            if score >= 0.75:
                verdict = "Likely AI-Generated"
                emoji = "🔴"
            elif score <= 0.4:
                verdict = "Likely Human-Generated"
                emoji = "🟢"
            else:
                verdict = "Inconclusive"
                emoji = "🟡"

            signals = []
            if digit_ratio > 0.02:
                signals.append(f"High digit density ({digit_ratio:.2%})")
            if currency_symbols:
                signals.append(f"Currency symbols detected ({currency_symbols})")
            if promo_phrases:
                signals.append("Promotional/pricing language present")
            if urls:
                signals.append("Contains URLs or domain-like tokens")
            if named_entities:
                signals.append("Named public figures mentioned")

            explanation = (
                "No Gemini SDK available; falling back to heuristic analysis. "
                "This is less accurate than model-based analysis."
            )

            details = "; ".join(signals) if signals else "No strong heuristics detected"

            return (
                f"{emoji} Verdict: {verdict} ({pct}% confidence)\n"
                f"Analysis: {explanation}\n"
                f"Signals: {details}\n"
                f"Preview: {s[:400]}"
            )

        out = rule_based_fallback(text)
        try:
            return escape_for_telegram(out)
        except Exception:
            return out

    except Exception as e:
        err = f"Gemini analysis unexpected error: {e}"
        try:
            return escape_for_telegram(err)
        except Exception:
            return err


async def detect_fake_image(image_path: str) -> dict:
    """Analyze an image for AI-generation signals and extract OCR text.

    Returns a dict with keys: caption, ocr_text, ai_signals, raw_response.
    """
    try:
        from ai_agent_adk import tools
    except Exception:
        tools = None

    # Try Gemini-powered analysis first (tools provides async analyse_image_with_gemini)
    if tools and hasattr(tools, 'analyse_image_with_gemini'):
        try:
            resp = await tools.analyse_image_with_gemini(image_path)
            # If tools already returned an error, fallthrough to local fallback
            if isinstance(resp, dict) and resp.get('error'):
                raise Exception(resp.get('error'))
            # Ensure values are telegram-safe
            resp_out = {
                'caption': escape_for_telegram(resp.get('caption', '') if isinstance(resp, dict) else str(resp)[:200]),
                'ocr_text': escape_for_telegram(resp.get('ocr_text', '')) if isinstance(resp, dict) else None,
                'ai_signals': escape_for_telegram(resp.get('ai_signals', '')) if isinstance(resp, dict) else '',
                'raw_response': resp.get('raw_response', resp) if isinstance(resp, dict) else resp,
            }
            return resp_out
        except Exception:
            pass

    # Fallback: local heuristics + OCR if available
    caption = ''
    ocr_text = None
    ai_signals = []
    raw = None
    try:
        from PIL import Image, ImageStat
        try:
            img = Image.open(image_path).convert('RGB')
            caption = f'Image {img.width}x{img.height}, mode={img.mode}'
            stat = ImageStat.Stat(img)
            avg_brightness = sum(stat.mean) / len(stat.mean)
            raw = {'size': (img.width, img.height), 'mean_brightness': avg_brightness}
        except Exception:
            img = None
    except Exception:
        img = None

    # OCR (optional dependency)
    try:
        import importlib
        pytesseract = importlib.import_module('pytesseract')
    except Exception:
        pytesseract = None

    if pytesseract:
        try:
            from PIL import Image
            ocr_text = pytesseract.image_to_string(Image.open(image_path)) or None
            if ocr_text:
                ai_signals.append('OCR text detected')
        except Exception:
            ocr_text = None
    else:
        ocr_text = None

    # Simple visual heuristic using OpenCV if available
    try:
        import cv2
        import numpy as np
        frame = cv2.imread(image_path)
        if frame is not None:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            if lap_var < 50:
                ai_signals.append('Very smooth/shallow detail (low Laplacian variance)')
            # detect many repeated blocks (simple autocorrelation proxy)
            h, w = gray.shape[:2]
            small = cv2.resize(gray, (max(16, w//8), max(16, h//8)))
            uniq = np.unique(small).size
            if uniq / (small.size) < 0.05:
                ai_signals.append('Low tonal variety (possible tiling/artifact)')
    except Exception:
        pass

    if not ai_signals:
        ai_signals = ['No strong local heuristics detected']

    out = {
        'caption': escape_for_telegram(caption),
        'ocr_text': escape_for_telegram(ocr_text) if ocr_text else None,
        'ai_signals': escape_for_telegram('; '.join(ai_signals)),
        'raw_response': raw,
    }
    return out


async def detect_fake_video(video_path: str, sample_every_seconds: float = 2.0) -> dict:
    """Analyze a video by sampling frames and aggregating image analysis.

    Returns dict with: frames_analyzed, aggregated_signals, ocr_texts (list), captions (list).
    """
    results = {'frames_analyzed': 0, 'aggregated_signals': [], 'ocr_texts': [], 'captions': []}
    try:
        import cv2
    except Exception:
        return {'error': 'OpenCV not available for video analysis'}

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {'error': 'Could not open video file'}
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_interval = int(max(1, fps * sample_every_seconds))
        idx = 0
        sampled = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if idx % frame_interval == 0:
                sampled += 1
                # write frame to temporary file and analyze
                import tempfile
                import os
                tmpf = None
                try:
                    fd, tmpf = tempfile.mkstemp(suffix='.jpg')
                    os.close(fd)
                    cv2.imwrite(tmpf, frame)
                    info = await detect_fake_image(tmpf)
                    results['frames_analyzed'] += 1
                    if info.get('ai_signals'):
                        results['aggregated_signals'].append(info.get('ai_signals'))
                    if info.get('ocr_text'):
                        results['ocr_texts'].append(info.get('ocr_text'))
                    if info.get('caption'):
                        results['captions'].append(info.get('caption'))
                finally:
                    try:
                        if tmpf and os.path.exists(tmpf):
                            os.remove(tmpf)
                    except Exception:
                        pass
            idx += 1
        cap.release()
        if not results['aggregated_signals']:
            results['aggregated_signals'] = ['No strong signals detected across frames']
        return results
    except Exception as e:
        return {'error': str(e)}


# ── Image Manipulation Detection (Gemini Vision) ─────────────────────────────

async def detect_image_manipulation(file_path: str) -> dict:
    """
    Detect image manipulation, deepfakes, and AI generation artifacts using Gemini Vision.

    Targets: GAN-generated faces, compositing seams, cloning artifacts,
    unnatural lighting/shadows, and DALL-E/Midjourney/Stable Diffusion patterns.

    Args:
        file_path: Local path to image file.

    Returns:
        dict: manipulation_detected (bool), manipulation_type (str),
              signals (list[str]), explanation (str), confidence (float)
    """
    gemini_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        logging.warning("[ImageManipulation] GEMINI_API_KEY not set")
        return {
            "manipulation_detected": False,
            "manipulation_type": "unknown",
            "signals": [],
            "explanation": "Image manipulation check unavailable (no API key).",
            "confidence": 0.0,
        }

    try:
        import google.genai as genai
        from PIL import Image

        os.environ.setdefault("GEMINI_API_KEY", gemini_key)
        os.environ.setdefault("GENAI_API_KEY", gemini_key)

        gemini_model_name = os.environ.get("MODEL_NAME", MODEL_NAME or "gemini-2.5-flash")

        prompt = """You are an expert in digital image forensics and AI-generated content detection.

Analyse this image for signs of manipulation or AI generation.
Respond in JSON format only — no markdown, no preamble:

{
  "manipulation_detected": true or false,
  "manipulation_type": "none | deepfake_face | gan_generated | compositing | cloning | ai_art | unknown",
  "signals": ["list of specific visual signals observed, empty array if none"],
  "explanation": "one paragraph plain-language explanation",
  "confidence": 0.0 to 1.0
}

Check for:
1. Deepfake/face-swap: unnatural skin texture, blending at face edges, asymmetric features
2. GAN generation: overly smooth textures, background inconsistencies, repeating patterns
3. Compositing: mismatched lighting or shadows, perspective errors, edge artefacts
4. Cloning/inpainting: repeated textures, smeared regions, unnatural blurring
5. AI art patterns: DALL-E/Midjourney/Stable Diffusion visual signatures

Be conservative — only flag when clear visual evidence is present."""

        def _call():
            try:
                Model = getattr(genai, "GenerativeModel", None)
                if Model is None:
                    return None
                try:
                    m = Model(gemini_model_name)
                except TypeError:
                    m = Model(gemini_model_name)
                img = Image.open(file_path)
                if hasattr(m, "generate_content"):
                    resp = m.generate_content([prompt, img])
                    return getattr(resp, "text", str(resp))
                return None
            except Exception:
                return None

        raw = await asyncio.to_thread(_call)
        if raw:
            clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE).strip()
            return json.loads(clean)
    except (json.JSONDecodeError, Exception) as e:
        logging.exception(f"[ImageManipulation] Detection failed: {e}")

    return {
        "manipulation_detected": False,
        "manipulation_type": "unknown",
        "signals": [],
        "explanation": "Image manipulation check unavailable.",
        "confidence": 0.0,
    }

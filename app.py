"""
app.py — FastAPI web server for SENTINEL detection pipeline.

Serves the web interface (static/index.html) and provides REST + WebSocket
endpoints for text, image, audio (Gemini Live API), and video analysis.
On startup, also launches the Telegram bot poller in a background thread.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import shutil
import os
import asyncio
import uuid
import logging
import base64
import json

from pipeline.detector import run_full_detection, detect_misinformation
from pipeline.guard import run_guard_detection
from pipeline.insights import run_insights
from pipeline.translator import detect_language, translate_to_english, translate_from_english
from pipeline.formatter import format_detection_message
from pipeline.predict_demo import get_demo_prediction
from config import (
    TELEGRAM_BACKGROUND_POLLER_ENABLED,
    TELEGRAM_WEBHOOK_ENABLED,
    TELEGRAM_WEBHOOK_PATH,
    TELEGRAM_WEBHOOK_SECRET,
)

# Optional media modules — may fail if dependencies are missing
try:
    from media.live import live_voice_exchange, InterruptibleLiveSession, _to_pcm, _pcm_to_ogg
except Exception:
    live_voice_exchange = None
    InterruptibleLiveSession = None
    _to_pcm = None
    _pcm_to_ogg = None

try:
    from media.image import extract_text_from_image, detect_image_manipulation, analyse_image_with_gemini
except Exception:
    extract_text_from_image = None
    detect_image_manipulation = None
    analyse_image_with_gemini = None

try:
    from media.audio import transcribe_audio
except Exception:
    transcribe_audio = None

try:
    from media.video import analyse_video
except Exception:
    analyse_video = None

logger = logging.getLogger(__name__)

# Audio MIME type mapping for file extensions
AUDIO_MIME_TYPES = {
    ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".webm": "audio/webm", ".mp4": "audio/mp4", ".m4a": "audio/mp4",
}


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Start Telegram in webhook mode (preferred) or poller mode (optional)."""
    webhook_started = False

    if TELEGRAM_WEBHOOK_ENABLED:
        if TELEGRAM_BACKGROUND_POLLER_ENABLED:
            logging.getLogger(__name__).warning(
                "Both TELEGRAM_WEBHOOK_ENABLED and TELEGRAM_BACKGROUND_POLLER_ENABLED are true; "
                "webhook mode takes precedence."
            )
        try:
            from telegram_bot import init_webhook_app
            webhook_started = await init_webhook_app()
            if not webhook_started:
                logging.getLogger(__name__).warning(
                    "Telegram webhook app failed to initialise; webhook endpoint will be unavailable."
                )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Telegram webhook init failed: %s — web server will continue without Telegram", exc
            )
    elif TELEGRAM_BACKGROUND_POLLER_ENABLED:
        try:
            from telegram_bot import start_bot_background
            start_bot_background()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Telegram bot failed to start: %s — web server will continue without it", exc
            )
    else:
        logging.getLogger(__name__).info(
            "Telegram startup disabled in web process "
            "(enable TELEGRAM_WEBHOOK_ENABLED for Cloud Run webhook mode)."
        )

    try:
        yield
    finally:
        if TELEGRAM_WEBHOOK_ENABLED and webhook_started:
            try:
                from telegram_bot import shutdown_webhook_app
                await shutdown_webhook_app()
            except Exception:
                logging.getLogger(__name__).warning("Telegram webhook shutdown failed", exc_info=True)


app = FastAPI(
    title="SENTINEL — AI Content Detection",
    description="Multimodal AI content detection: text, image, audio (Gemini Live API), and video analysis.",
    version="2.0.0",
    lifespan=lifespan,
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Serve static files (web interface)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _safe_path(filename: str) -> str:
    """Generate a safe upload path using a UUID prefix to avoid path traversal."""
    safe_name = os.path.basename(filename or "upload")
    return os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{safe_name}")


# ── Web Interface ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the SENTINEL web interface."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>SENTINEL API running</h1><p>Web interface not found.</p>")


@app.get("/health")
def health():
    """Health check endpoint for Cloud Run."""
    return {"status": "healthy", "service": "sentinel"}


@app.get("/health/telegram")
async def health_telegram():
    """Telegram runtime diagnostics for webhook/poller mode verification."""
    diagnostics = {
        "webhook_enabled": TELEGRAM_WEBHOOK_ENABLED,
        "background_poller_enabled": TELEGRAM_BACKGROUND_POLLER_ENABLED,
        "webhook_path": TELEGRAM_WEBHOOK_PATH,
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "webhook_ready": False,
        "webhook_running": False,
    }

    try:
        from telegram_bot import get_telegram_runtime_status
        runtime = get_telegram_runtime_status() or {}
        diagnostics["webhook_ready"] = bool(runtime.get("webhook_ready", False))
        diagnostics["webhook_running"] = bool(runtime.get("webhook_running", False))
    except Exception as exc:
        diagnostics["error"] = str(exc)

    return diagnostics


@app.post(TELEGRAM_WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Telegram webhook endpoint for Cloud Run (no polling/getUpdates)."""
    if not TELEGRAM_WEBHOOK_ENABLED:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Webhook mode disabled"})

    if TELEGRAM_WEBHOOK_SECRET and x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET:
        return JSONResponse(status_code=403, content={"ok": False, "error": "Invalid webhook secret"})

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid JSON payload"})

    try:
        from telegram_bot import process_webhook_update
        processed = await process_webhook_update(payload)
    except Exception as exc:
        logger.warning("[API] Telegram webhook processing failed: %s", exc)
        processed = False

    if not processed:
        return JSONResponse(status_code=503, content={"ok": False, "error": "Telegram app unavailable"})

    return {"ok": True}


# ── Text Detection ────────────────────────────────────────────────────────────

@app.post("/detect-text")
async def detect_text(text: str = Form(...)):
    """Analyse text using the GUARD + misinformation pipeline."""
    try:
        result = await run_guard_detection(text, content_type="text", source_lang="en")
        return {"analysis": result}
    except Exception as e:
        logger.exception("[API] Text detection failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Misinformation Detection ─────────────────────────────────────────────────

@app.post("/detect-misinformation")
async def detect_misinfo_endpoint(
    text: str = Form(...),
    context: str = Form(""),
):
    """
    Detect AI-assisted misinformation in text content.
    """
    try:
        result = await detect_misinformation(text, context_description=context)
        return {"analysis": result}
    except Exception as e:
        logger.exception("[API] Misinformation detection failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Image Detection ───────────────────────────────────────────────────────────

@app.post("/detect-image")
async def detect_image(file: UploadFile = File(...)):
    """Analyse an image for AI-generation signals and extract OCR text."""
    if extract_text_from_image is None:
        return JSONResponse(status_code=503, content={"error": "Image detection not available"})
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await extract_text_from_image(path)
        return {"analysis": result}
    except Exception as e:
        logger.exception("[API] Image detection failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Image Manipulation Detection ──────────────────────────────────────────────

@app.post("/detect-image-manipulation")
async def detect_manipulation_endpoint(file: UploadFile = File(...)):
    """
    Detect image manipulation, deepfakes, and AI generation artifacts.
    """
    if detect_image_manipulation is None:
        return JSONResponse(status_code=503, content={"error": "Image manipulation detection not available"})
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await detect_image_manipulation(path)
        return {"analysis": result}
    except Exception as e:
        logger.exception("[API] Image manipulation detection failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── OCR Text Extraction ──────────────────────────────────────────────────────

@app.post("/ocr")
async def ocr_endpoint(file: UploadFile = File(...)):
    """
    Extract text from an image using Gemini Vision OCR with Tesseract fallback.
    """
    if extract_text_from_image is None:
        return JSONResponse(status_code=503, content={"error": "OCR not available"})
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await extract_text_from_image(path)
        return {"ocr": result}
    except Exception as e:
        logger.exception("[API] OCR failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Video Detection ───────────────────────────────────────────────────────────

@app.post("/detect-video")
async def detect_video(file: UploadFile = File(...)):
    """Analyse a video by sampling frames for AI-generation signals."""
    if analyse_video is None:
        return JSONResponse(status_code=503, content={"error": "Video detection not available"})
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await analyse_video(path)
        return {"analysis": result}
    except Exception as e:
        logger.exception("[API] Video detection failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Full Pipeline (text) ─────────────────────────────────────────────────────

@app.post("/analyse")
async def full_analysis(text: str = Form(...)):
    """
    Run the full detection pipeline: GUARD + misinformation + insights.
    """
    try:
        result = await run_full_detection(text, content_type="text", source_lang="en")
        return result
    except Exception as e:
        logger.exception("[API] Full analysis failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── SSE Streaming Pipeline (ContextGuard pattern) ────────────────────────────


class AnalyseStreamRequest(BaseModel):
    text: str


class PredictStreamRequest(BaseModel):
    text: str


@app.post("/analyse-stream")
async def analyse_stream(body: AnalyseStreamRequest):
    """
    Run the full detection pipeline with SSE streaming progress updates.

    Streams step-by-step progress (GUARD → Misinformation → Insights)
    in real time using Server-Sent Events, following the ContextGuard pattern.

    Event types:
    - step: {id, status, data?} — pipeline step status update
    - result: full detection result object
    """
    text = body.text
    if not text or not text.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Text is required"},
        )

    async def generate():
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        try:
            # Step 0: Language detection and translation
            source_lang = detect_language(text) if len(text) >= 20 else "en"
            english_text = text
            if source_lang != "en":
                yield sse("step", {"id": "translate", "status": "running", "data": {"source_lang": source_lang}})
                try:
                    english_text = await translate_to_english(text, source_lang)
                except Exception as exc:
                    logger.warning("[SSE] Translation failed: %s", exc)
                    english_text = text
                yield sse("step", {"id": "translate", "status": "done", "data": {"source_lang": source_lang, "translated": source_lang != "en"}})

            # Step 1: GUARD detection
            yield sse("step", {"id": "guard", "status": "running"})
            try:
                guard_result = await run_guard_detection(
                    english_text, content_type="text", source_lang=source_lang
                )
            except Exception as exc:
                logger.exception("[SSE] GUARD detection failed: %s", exc)
                guard_result = {
                    "is_safe": None,
                    "label": "api_error",
                    "raw_response": {},
                    "safety_flag": None,
                }
            yield sse("step", {"id": "guard", "status": "done", "data": guard_result})

            # Step 2: Misinformation detection
            yield sse("step", {"id": "misinfo", "status": "running"})
            try:
                misinfo_result = await detect_misinformation(
                    english_text, context_description="text"
                )
            except Exception as exc:
                logger.exception("[SSE] Misinfo detection failed: %s", exc)
                misinfo_result = {
                    "misinformation_detected": False,
                    "misinformation_type": "none",
                    "claims": [],
                    "explanation": "Unavailable.",
                }
            yield sse("step", {"id": "misinfo", "status": "done", "data": misinfo_result})

            # Step 3: Insights
            yield sse("step", {"id": "insights", "status": "running"})
            try:
                insights_result = await run_insights(
                    english_text, guard_result, misinformation_result=misinfo_result
                )
            except Exception as exc:
                logger.exception("[SSE] Insights failed: %s", exc)
                insights_result = {}
            yield sse("step", {"id": "insights", "status": "done", "data": insights_result})

            # Step 4: Translate explanation back to source language
            explanation = (insights_result or {}).get("explanation", "")
            misinfo_explanation = misinfo_result.get("explanation", "")
            if source_lang != "en":
                try:
                    if explanation:
                        translated_explanation = await translate_from_english(explanation, source_lang)
                        insights_result = {**insights_result, "explanation": translated_explanation, "original_explanation": explanation}
                    if misinfo_explanation and misinfo_explanation != "Unavailable.":
                        translated_misinfo = await translate_from_english(misinfo_explanation, source_lang)
                        misinfo_result = {**misinfo_result, "explanation": translated_misinfo, "original_explanation": misinfo_explanation}
                except Exception as exc:
                    logger.warning("[SSE] Translation back failed: %s", exc)

            # Compute combined verdict
            guard_safe = guard_result.get("is_safe")
            misinfo_detected = misinfo_result.get("misinformation_detected", False)
            is_harmful = (insights_result or {}).get("is_harmful", False)

            if guard_safe is None:
                combined_is_safe = None
            elif guard_safe is False or misinfo_detected or is_harmful:
                combined_is_safe = False
            else:
                combined_is_safe = True

            full_result = {
                "detection_result": guard_result,
                "misinfo_result": misinfo_result,
                "manipulation_result": None,
                "insights_result": insights_result,
                "is_safe": combined_is_safe,
                "misinfo_type": misinfo_result.get("misinformation_type", "none"),
                "source_lang": source_lang,
            }

            yield sse("result", full_result)

        except Exception as exc:
            logger.exception("[SSE] Stream error: %s", exc)
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Proactive Prediction (demo SSE streaming) ───────────────────────────────


@app.post("/predict-stream")
async def predict_stream(body: PredictStreamRequest):
    """Demo rumour prediction stream following the ContextGuard SSE pattern."""
    text = body.text
    if not text or not text.strip():
        return JSONResponse(status_code=400, content={"error": "Text is required"})

    async def generate():
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        try:
            payload = get_demo_prediction(text)
            topics = payload.get("topics") or {}
            sources = payload.get("sources") or []

            yield sse("step", {"id": "topics", "status": "running"})
            yield sse("step", {"id": "topics", "status": "done", "data": topics})

            yield sse("step", {"id": "sources", "status": "running"})
            for src in sources:
                try:
                    url = (src or {}).get("url", "")
                    domain = ""
                    if url:
                        try:
                            domain = url.split("//", 1)[1].split("/", 1)[0]
                        except Exception:
                            domain = ""
                    yield sse(
                        "source",
                        {
                            "label": (src or {}).get("label", "Source"),
                            "url": url,
                            "domain": domain,
                        },
                    )
                except Exception:
                    continue
            yield sse("step", {"id": "sources", "status": "done"})

            yield sse("step", {"id": "analyze", "status": "running"})
            yield sse("step", {"id": "analyze", "status": "done"})

            result = {
                "topics": topics,
                "predictions": payload.get("predictions", []),
                "historicalPatterns": payload.get("historicalPatterns", []),
                "communityLeadersCount": payload.get("communityLeadersCount", 0),
                "constituencies": payload.get("constituencies", []),
                "sources": sources,
            }
            yield sse("result", result)
        except Exception as exc:
            logger.exception("[Predict SSE] Stream error: %s", exc)
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Full Image Analysis (SSE streaming) ───────────────────────────────────────

@app.post("/analyse-image-stream")
async def analyse_image_stream(file: UploadFile = File(...)):
    """
    Run the full image detection pipeline with SSE streaming progress.

    Pipeline: Gemini Visual → GUARD → Misinformation → Manipulation → Insights.
    Mirrors telegram_bot.py handle_photo behaviour.
    """
    if analyse_image_with_gemini is None:
        return JSONResponse(status_code=503, content={"error": "Image analysis not available"})

    path = _safe_path(file.filename)
    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    async def generate():
        def sse(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        try:
            # Step 1: Gemini visual analysis (caption, OCR, AI signals)
            yield sse("step", {"id": "vision", "status": "running"})
            try:
                gemini_vis = await analyse_image_with_gemini(path)
            except Exception as exc:
                logger.exception("[SSE-Image] Gemini vision failed: %s", exc)
                gemini_vis = {"caption": "", "ocr_text": None, "ai_signals": "", "error": str(exc)}
            yield sse("step", {"id": "vision", "status": "done", "data": gemini_vis})

            caption = gemini_vis.get("caption", "")
            ocr_text = gemini_vis.get("ocr_text") or ""
            ai_signals = gemini_vis.get("ai_signals", "")

            # Build text input for detection pipeline
            guard_input = f"Image description: {caption}"
            if ocr_text:
                guard_input += f"\nExtracted text: {ocr_text}"
            if ai_signals:
                guard_input += f"\nVisual AI signals: {ai_signals}"

            # Step 2: GUARD safety check
            yield sse("step", {"id": "guard", "status": "running"})
            try:
                guard_result = await run_guard_detection(
                    guard_input, content_type="image", source_lang="en"
                )
            except Exception as exc:
                logger.exception("[SSE-Image] GUARD failed: %s", exc)
                guard_result = {
                    "is_safe": None, "label": "api_error",
                    "raw_response": {}, "safety_flag": None,
                }
            yield sse("step", {"id": "guard", "status": "done", "data": guard_result})

            # Step 3: Misinformation detection
            yield sse("step", {"id": "misinfo", "status": "running"})
            try:
                misinfo_result = await detect_misinformation(
                    guard_input, context_description="image"
                )
            except Exception as exc:
                logger.exception("[SSE-Image] Misinfo failed: %s", exc)
                misinfo_result = {
                    "misinformation_detected": False, "misinformation_type": "none",
                    "claims": [], "explanation": "Unavailable.",
                }
            yield sse("step", {"id": "misinfo", "status": "done", "data": misinfo_result})

            # Step 4: Image manipulation detection (OpenCV heuristics)
            yield sse("step", {"id": "manipulation", "status": "running"})
            manipulation_result = None
            if detect_image_manipulation is not None:
                try:
                    manipulation_result = await detect_image_manipulation(path)
                except Exception as exc:
                    logger.exception("[SSE-Image] Manipulation failed: %s", exc)
            if manipulation_result is None:
                manipulation_result = {
                    "manipulation_detected": False, "manipulation_type": "none",
                    "signals": [], "explanation": "Check unavailable.", "confidence": 0.0,
                }
            yield sse("step", {"id": "manipulation", "status": "done", "data": manipulation_result})

            # Step 5: AI Insights
            yield sse("step", {"id": "insights", "status": "running"})
            try:
                insights_result = await run_insights(
                    guard_input, guard_result,
                    misinformation_result=misinfo_result,
                    manipulation_result=manipulation_result,
                )
            except Exception as exc:
                logger.exception("[SSE-Image] Insights failed: %s", exc)
                insights_result = {"explanation": "Unavailable.", "is_harmful": False, "llm_used": "failed"}
            yield sse("step", {"id": "insights", "status": "done", "data": insights_result})

            # Compute combined verdict
            guard_safe = guard_result.get("is_safe")
            misinfo_detected = misinfo_result.get("misinformation_detected", False)
            manip_detected = (manipulation_result or {}).get("manipulation_detected", False)
            is_harmful = (insights_result or {}).get("is_harmful", False)

            if guard_safe is None:
                combined_is_safe = None
            elif guard_safe is False or misinfo_detected or manip_detected or is_harmful:
                combined_is_safe = False
            else:
                combined_is_safe = True

            full_result = {
                "detection_result": guard_result,
                "misinfo_result": misinfo_result,
                "manipulation_result": manipulation_result,
                "insights_result": insights_result,
                "image_analysis": {
                    "caption": caption,
                    "ocr_text": ocr_text,
                    "ai_signals": ai_signals,
                },
                "is_safe": combined_is_safe,
                "misinfo_type": misinfo_result.get("misinformation_type", "none"),
            }

            yield sse("result", full_result)

        except Exception as exc:
            logger.exception("[SSE-Image] Stream error: %s", exc)
            yield sse("error", {"message": str(exc)})
        finally:
            if os.path.exists(path):
                os.remove(path)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ── Audio / Gemini Live API ───────────────────────────────────────────────────


async def _run_audio_pipeline(audio_bytes: bytes, audio_path: str, mime_type: str) -> dict:
    """
    Shared audio processing: transcribe → detect → Live API.

    Returns dict with transcript, detection results, and Live API audio.
    Mirrors telegram_bot.py handle_audio behaviour.
    """
    result = {
        "transcript": "",
        "detected_language": "en",
        "detection_result": None,
        "misinfo_result": None,
        "insights_result": None,
        "is_safe": None,
        "audio": "",
        "mime_type": "audio/ogg",
        "success": False,
    }

    # Step 1: Transcribe with Deepgram
    if transcribe_audio is not None and audio_path:
        try:
            transcript_result = await transcribe_audio(audio_path)
            result["transcript"] = transcript_result.get("transcript", "")
            result["detected_language"] = transcript_result.get("detected_language", "en")
        except Exception as e:
            logger.warning("[Audio] Transcription failed: %s", e)

    transcript = result["transcript"]

    # Step 2: Run full detection pipeline on transcript (if long enough)
    detection_context = ""
    if transcript and len(transcript) >= 20:
        try:
            english_text = transcript
            full_result = await run_full_detection(
                english_text, content_type="audio", source_lang=result["detected_language"]
            )
            result["detection_result"] = full_result.get("detection_result")
            result["misinfo_result"] = full_result.get("misinfo_result")
            result["insights_result"] = full_result.get("insights_result")
            result["is_safe"] = full_result.get("is_safe")
            result["misinfo_type"] = full_result.get("misinfo_type", "none")

            # Build context string for Live API
            explanation = (full_result.get("insights_result") or {}).get("explanation", "")
            guard_safe = (full_result.get("detection_result") or {}).get("is_safe")
            misinfo = (full_result.get("misinfo_result") or {}).get("misinformation_detected", False)

            parts = []
            if guard_safe is False:
                parts.append("GUARD flagged this content as unsafe.")
            if misinfo:
                parts.append(f"Misinformation detected: {full_result.get('misinfo_type', 'unknown')}.")
            if explanation:
                parts.append(explanation)
            detection_context = " ".join(parts) if parts else "Content analysed. No issues found."
        except Exception as e:
            logger.warning("[Audio] Detection pipeline failed: %s", e)

    if not detection_context:
        detection_context = f"Audio transcript: {transcript[:200]}" if transcript else "User submitted audio for analysis."

    # Step 3: Get spoken verdict from Gemini Live API
    try:
        reply_ogg = await live_voice_exchange(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            system_context=detection_context,
        )
        if reply_ogg:
            result["audio"] = base64.b64encode(reply_ogg).decode("utf-8")
            result["success"] = True
    except Exception as e:
        logger.warning("[Audio] Live API failed: %s", e)

    return result


@app.post("/analyse-audio")
async def analyse_audio(file: UploadFile = File(...)):
    """
    Full audio analysis: Deepgram transcription → GUARD + misinformation →
    insights → Gemini Live API spoken verdict.

    Returns transcription, detection results, AND base64-encoded OGG audio.
    """
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with open(path, "rb") as f:
            audio_bytes = f.read()

        ext = os.path.splitext(file.filename or "")[1].lower()
        mime_type = AUDIO_MIME_TYPES.get(ext, "audio/webm")

        return await _run_audio_pipeline(audio_bytes, path, mime_type)

    except Exception as e:
        logger.exception("[API] Audio analysis failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── WebSocket — Gemini Live API real-time audio ───────────────────────────────

@app.websocket("/ws/live-audio")
async def websocket_live_audio(websocket: WebSocket):
    """
    WebSocket endpoint for real-time Gemini Live API audio exchange.

    Full pipeline: transcribe → detect → Live API spoken verdict.

    Protocol:
    1. Client sends binary audio frames (WebM/OGG chunks)
    2. Client sends text message "END" to signal recording complete
    3. Server transcribes, runs detection, then processes with Live API
    4. Server sends back JSON with transcript, detection results, and audio
    5. Server sends text "DONE" to signal completion
    """
    await websocket.accept()
    audio_chunks: list[bytes] = []
    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message:
                audio_chunks.append(message["bytes"])
            elif "text" in message:
                text = message["text"]
                if text == "END":
                    audio_data = b"".join(audio_chunks)
                    audio_chunks.clear()

                    if not audio_data:
                        await websocket.send_json({"error": "No audio data received"})
                        await websocket.send_text("DONE")
                        continue

                    # Save temp file for transcription
                    tmp_path = _safe_path("ws_audio.webm")
                    try:
                        with open(tmp_path, "wb") as f:
                            f.write(audio_data)

                        result = await _run_audio_pipeline(audio_data, tmp_path, "audio/webm")
                        await websocket.send_json(result)
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)

                    await websocket.send_text("DONE")

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.exception("[WS] Live audio error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass


# ── WebSocket — Live Agent (bidirectional streaming with interruption) ────────

@app.websocket("/ws/live-agent")
async def websocket_live_agent(websocket: WebSocket):
    """
    Bidirectional streaming Live Agent using InterruptibleLiveSession.

    Protocol:
    - Client sends binary frames: raw PCM16 mono 16kHz audio chunks
    - Client sends JSON: {"type":"text","content":"..."} for text input
    - Client sends JSON: {"type":"image","content":"<base64>","mime_type":"image/jpeg"}
    - Client sends JSON: {"type":"end_turn"} when user stops speaking
    - Client sends JSON: {"type":"webm_audio","content":"<base64>"} for WebM audio
    - Server sends binary frames: PCM16 audio chunks from model
    - Server sends JSON: {"type":"turn_start"} when model starts speaking
    - Server sends JSON: {"type":"turn_end"} when model finishes
    - Server sends JSON: {"type":"interrupted"} when model is interrupted
    - Server sends JSON: {"type":"connected"} when session is ready
    - Server sends JSON: {"type":"error","message":"..."} on error
    """
    await websocket.accept()
    session: InterruptibleLiveSession | None = None
    response_task: asyncio.Task | None = None

    async def stream_responses():
        """Forward model audio chunks to the WebSocket client."""
        try:
            while session and not session._closed:
                sent_turn_start = False
                async for chunk in session.receive_audio():
                    try:
                        if not sent_turn_start:
                            await websocket.send_json({"type": "turn_start"})
                            sent_turn_start = True
                        # Convert PCM chunk to base64 for JSON transport
                        await websocket.send_json({
                            "type": "audio",
                            "data": base64.b64encode(chunk).decode("utf-8"),
                        })
                    except Exception:
                        return
                try:
                    if session.last_receive_interrupted:
                        await websocket.send_json({"type": "interrupted"})
                    elif sent_turn_start:
                        await websocket.send_json({"type": "turn_end"})
                except Exception:
                    return
                sent_turn_start = False
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("[Live Agent WS] Response stream error: %s", e)

    try:
        session = InterruptibleLiveSession(
            system_context="You are SENTINEL, an AI content detection assistant. "
            "Help users analyse text, images, and audio for AI generation, "
            "misinformation, and manipulation. Speak naturally and concisely."
        )
        await session.connect()
        await websocket.send_json({"type": "connected"})

        response_task = asyncio.create_task(stream_responses())

        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message:
                # Raw PCM16 audio chunk from client mic
                await session.send_audio(message["bytes"])

            elif "text" in message:
                try:
                    data = json.loads(message["text"])
                except (json.JSONDecodeError, TypeError):
                    continue

                msg_type = data.get("type", "")

                if msg_type == "text":
                    content = data.get("content", "").strip()
                    if content:
                        await session.send_text(content)

                elif msg_type == "image":
                    img_b64 = data.get("content", "")
                    mime = data.get("mime_type", "image/jpeg")
                    if img_b64:
                        img_bytes = base64.b64decode(img_b64)
                        await session.send_image(img_bytes, mime)

                elif msg_type == "end_turn":
                    await session.end_turn()

                elif msg_type == "interrupt":
                    if session:
                        await session.interrupt()
                        # Explicitly notify client that the model was interrupted.
                        # This ensures clients always receive an "interrupted" event,
                        # even if the response-stream task later emits "turn_end".
                        await websocket.send_json({"type": "interrupted"})

                elif msg_type == "webm_audio":
                    # Client sent WebM-encoded audio — convert to PCM
                    audio_b64 = data.get("content", "")
                    if audio_b64:
                        webm_bytes = base64.b64decode(audio_b64)
                        pcm = _to_pcm(webm_bytes, "audio/webm")
                        if pcm:
                            # Send in chunks to enable interruption
                            chunk_size = 3200  # 100ms at 16kHz mono
                            for i in range(0, len(pcm), chunk_size):
                                await session.send_audio(pcm[i:i + chunk_size])
                                await asyncio.sleep(0.02)

    except WebSocketDisconnect:
        logger.info("[Live Agent WS] Client disconnected")
    except Exception as e:
        logger.exception("[Live Agent WS] Error: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        if response_task and not response_task.done():
            response_task.cancel()
            try:
                await response_task
            except (asyncio.CancelledError, Exception):
                pass
        if session:
            await session.close()


# ── Research Agent ────────────────────────────────────────────────────────────


class ResearchRequest(BaseModel):
    query: str


@app.post("/research")
async def research_endpoint(body: ResearchRequest):
    """
    Run web research on a query using the research agent.

    Returns research summary, sources, and paths.
    """
    query = body.query.strip()
    if not query:
        return JSONResponse(status_code=400, content={"error": "Query is required"})

    try:
        from research_agent.agent import research

        result = await research(query)

        summary_text = ""
        summary_path = result.get("summary_path")
        if not summary_path and result.get("cache_hit"):
            summary_path = result.get("skill_path")

        if summary_path and os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_text = f.read()

        response = {
            "summary": summary_text,
            "sources": result.get("sources", []),
            "cache_hit": result.get("cache_hit", False),
            "llm_used": result.get("llm_used", ""),
        }
        if result.get("error"):
            response["error"] = result["error"]
        return response
    except ImportError:
        return JSONResponse(status_code=503, content={"error": "Research agent not available"})
    except Exception as e:
        logger.exception("[API] Research failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

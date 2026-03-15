"""
app.py — FastAPI web server for SENTINEL detection pipeline.

Serves the web interface (static/index.html) and provides REST + WebSocket
endpoints for text, image, audio (Gemini Live API), and video analysis.
"""

from fastapi import FastAPI, UploadFile, File, Form, Query, WebSocket, WebSocketDisconnect
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
from media.live import live_voice_exchange

# Optional media modules — may fail if dependencies are missing
try:
    from media.image import extract_text_from_image, detect_image_manipulation
except Exception:
    extract_text_from_image = None
    detect_image_manipulation = None

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

app = FastAPI(
    title="SENTINEL — AI Content Detection",
    description="Multimodal AI content detection: text, image, audio (Gemini Live API), and video analysis.",
    version="2.0.0",
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
            # Step 1: GUARD detection
            yield sse("step", {"id": "guard", "status": "running"})
            try:
                guard_result = await run_guard_detection(
                    text, content_type="text", source_lang="en"
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
                    text, context_description="text"
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
                    text, guard_result, misinformation_result=misinfo_result
                )
            except Exception as exc:
                logger.exception("[SSE] Insights failed: %s", exc)
                insights_result = {}
            yield sse("step", {"id": "insights", "status": "done", "data": insights_result})

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


# ── Audio / Gemini Live API ───────────────────────────────────────────────────

@app.post("/analyse-audio")
async def analyse_audio(file: UploadFile = File(...)):
    """
    Send audio to Gemini Live API for spoken verdict.
    Returns base64-encoded OGG audio.
    """
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        with open(path, "rb") as f:
            audio_bytes = f.read()

        # Determine MIME type from filename
        ext = os.path.splitext(file.filename or "")[1].lower()
        mime_type = AUDIO_MIME_TYPES.get(ext, "audio/webm")

        reply_ogg = await live_voice_exchange(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            system_context="User submitted audio for analysis via web interface.",
        )

        if reply_ogg:
            return {
                "audio": base64.b64encode(reply_ogg).decode("utf-8"),
                "mime_type": "audio/ogg",
                "success": True,
            }
        return {"audio": "", "success": False, "error": "Live API returned no audio"}
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

    Protocol:
    1. Client sends binary audio frames (WebM/OGG chunks)
    2. Client sends text message "END" to signal recording complete
    3. Server processes with Gemini Live API
    4. Server sends back base64-encoded OGG audio response
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
                    # Process collected audio
                    audio_data = b"".join(audio_chunks)
                    audio_chunks.clear()

                    if not audio_data:
                        await websocket.send_json({"error": "No audio data received"})
                        await websocket.send_text("DONE")
                        continue

                    reply_ogg = await live_voice_exchange(
                        audio_bytes=audio_data,
                        mime_type="audio/webm",
                        system_context="User is speaking to SENTINEL via web interface for real-time content analysis.",
                    )

                    if reply_ogg:
                        audio_b64 = base64.b64encode(reply_ogg).decode("utf-8")
                        await websocket.send_json({
                            "audio": audio_b64,
                            "mime_type": "audio/ogg",
                            "success": True,
                        })
                    else:
                        await websocket.send_json({
                            "success": False,
                            "error": "Gemini Live API returned no audio",
                        })

                    await websocket.send_text("DONE")

    except WebSocketDisconnect:
        logger.info("[WS] Client disconnected")
    except Exception as e:
        logger.exception("[WS] Live audio error: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
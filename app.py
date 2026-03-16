from fastapi import FastAPI, UploadFile, File, Form, Query
from fastapi.responses import JSONResponse
import shutil
import os
import asyncio
import uuid
import logging

from media.image import (
    extract_text_from_image,
    analyse_image_with_gemini,
    detect_image_manipulation,
)
from media.video import analyse_video

# Import detection tools from pipeline
try:
    from pipeline.guard import run_guard_detection
    from pipeline.insights import run_insights
    from pipeline.detector import detect_misinformation, run_full_detection
except Exception:
    run_guard_detection = None
    run_insights = None
    detect_misinformation = None
    run_full_detection = None

app = FastAPI(
    title="Fake Media Detector API",
    description="AI misinformation detection, image manipulation detection, OCR extraction, and video frame analysis.",
    version="1.0.0",
)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _safe_path(filename: str) -> str:
    """Generate a safe upload path using a UUID prefix to avoid path traversal."""
    safe_name = os.path.basename(filename or "upload")
    return os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{safe_name}")


@app.get("/")
def root():
    return {"message": "Fake Media Detector API running"}


# ── Text Detection ────────────────────────────────────────────────────────────

@app.post("/detect-text")
async def detect_text(text: str = Form(...)):
    """Analyse text for AI-generation signals using the detection pipeline."""
    if run_full_detection is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Text detection not available"},
        )
    result = await run_full_detection(text, content_type="text")
    return {"analysis": result}


# ── Misinformation Detection ─────────────────────────────────────────────────

@app.post("/detect-misinformation")
async def detect_misinfo_endpoint(
    text: str = Form(...),
    context: str = Form(""),
):
    """
    Detect AI-assisted misinformation in text content.
    Returns: misinformation_detected, misinformation_type, claims, explanation, confidence.
    """
    if detect_misinformation is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Misinformation detection not available"},
        )
    result = await detect_misinformation(text, context_description=context)
    return {"analysis": result}


# ── Image Detection ───────────────────────────────────────────────────────────

@app.post("/detect-image")
async def detect_image(file: UploadFile = File(...)):
    """Analyse an image for AI-generation signals and extract OCR text."""
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await analyse_image_with_gemini(path)
        return {"analysis": result}
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Image Manipulation Detection ──────────────────────────────────────────────

@app.post("/detect-image-manipulation")
async def detect_manipulation_endpoint(file: UploadFile = File(...)):
    """
    Detect image manipulation, deepfakes, and AI generation artifacts.
    Returns: manipulation_detected, manipulation_type, signals, explanation, confidence.
    """
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await detect_image_manipulation(path)
        return {"analysis": result}
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── OCR Text Extraction ──────────────────────────────────────────────────────

@app.post("/ocr")
async def ocr_endpoint(file: UploadFile = File(...)):
    """
    Extract text from an image using Gemini Vision OCR with Tesseract fallback.
    Returns: text, confidence, method.
    """
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await extract_text_from_image(path)
        return {"ocr": result}
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Video Detection ───────────────────────────────────────────────────────────

@app.post("/detect-video")
async def detect_video(file: UploadFile = File(...)):
    """Analyse a video by sampling frames for AI-generation signals."""
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await analyse_video(path)
        return {"analysis": result}
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Video Frame Analysis ─────────────────────────────────────────────────────

@app.post("/analyse-video-frames")
async def analyse_video_frames_endpoint(
    file: UploadFile = File(...),
    sample_every_seconds: float = Query(2.0, ge=0.5, le=10.0),
):
    """
    Analyse video by sampling frames — OCR extraction + AI signal analysis.
    Returns: frame_descriptions, audio_transcript, ai_signals, frames_checked, error.

    Note: sample_every_seconds is accepted for API compatibility but not yet
    used by the underlying analyse_video() implementation.
    """
    path = _safe_path(file.filename)
    try:
        with open(path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        result = await analyse_video(path)
        return {"analysis": result}
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Full Pipeline (text) ─────────────────────────────────────────────────────

@app.post("/analyse")
async def full_analysis(text: str = Form(...)):
    """
    Run the full detection pipeline: GUARD + misinformation + insights.
    """
    results = {"guard": None, "misinformation": None, "insights": None}

    coros = []
    if run_guard_detection is not None:
        coros.append(run_guard_detection(text, source_lang="en"))
    else:
        coros.append(asyncio.sleep(0))

    if detect_misinformation is not None:
        coros.append(detect_misinformation(text, context_description="api_text"))
    else:
        coros.append(asyncio.sleep(0))

    gathered = await asyncio.gather(*coros, return_exceptions=True)

    if run_guard_detection is not None and not isinstance(gathered[0], BaseException):
        results["guard"] = gathered[0]
    if detect_misinformation is not None and not isinstance(gathered[1], BaseException):
        results["misinformation"] = gathered[1]

    if run_insights is not None:
        try:
            results["insights"] = await run_insights(
                text,
                results["guard"] or {},
                misinformation_result=results["misinformation"],
            )
        except Exception as e:
            results["insights"] = {"error": str(e)}

    return results
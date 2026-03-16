"""
tests/test_app.py — Tests for the FastAPI web server (app.py).

Covers:
- Health check endpoint
- Web interface serving
- Text analysis endpoint
- Audio analysis endpoint (Gemini Live API)
- WebSocket live audio endpoint

All external API calls are mocked — no real network requests.
"""

import base64
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health & UI
# ---------------------------------------------------------------------------

def test_health_endpoint(client):
    """Health check returns 200 with status healthy."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"


def test_root_serves_html(client):
    """Root serves the web interface HTML page."""
    res = client.get("/")
    assert res.status_code == 200
    assert "SENTINEL" in res.text
    assert "text/html" in res.headers["content-type"]


def test_root_html_copy_buttons_pass_click_event(client):
    """Copy button handlers pass the click event explicitly."""
    res = client.get("/")
    assert res.status_code == 200
    assert 'onclick="copyResults(event)"' in res.text
    assert 'onclick="copyImageResults(event)"' in res.text


def test_root_html_copy_helpers_are_event_safe(client):
    """Copy helper functions guard when click event/button is unavailable."""
    res = client.get("/")
    assert res.status_code == 200
    assert "function copyResults(clickEvent)" in res.text
    assert "function copyImageResults(clickEvent)" in res.text
    assert "if (!btn) return;" in res.text


# ---------------------------------------------------------------------------
# Text detection
# ---------------------------------------------------------------------------

def test_detect_text_endpoint(client):
    """POST /detect-text returns analysis result."""
    mock_result = {"is_safe": True, "label": "safe", "raw_response": {}}
    with patch("app.run_guard_detection", new_callable=AsyncMock, return_value=mock_result):
        res = client.post("/detect-text", data={"text": "Hello world"})
    assert res.status_code == 200
    assert "analysis" in res.json()


def test_detect_misinformation_endpoint(client):
    """POST /detect-misinformation returns analysis result."""
    mock_result = {"misinformation_detected": False, "explanation": "Clean"}
    with patch("app.detect_misinformation", new_callable=AsyncMock, return_value=mock_result):
        res = client.post("/detect-misinformation", data={"text": "Test content"})
    assert res.status_code == 200
    assert "analysis" in res.json()


def test_full_analysis_endpoint(client):
    """POST /analyse runs the full pipeline."""
    mock_result = {
        "detection_result": {"is_safe": True},
        "misinfo_result": {"misinformation_detected": False},
        "manipulation_result": None,
        "insights_result": {},
        "is_safe": True,
        "misinfo_type": "none",
    }
    with patch("app.run_full_detection", new_callable=AsyncMock, return_value=mock_result):
        res = client.post("/analyse", data={"text": "Test analysis"})
    assert res.status_code == 200
    data = res.json()
    assert data["is_safe"] is True


# ---------------------------------------------------------------------------
# SSE Streaming Pipeline (ContextGuard pattern)
# ---------------------------------------------------------------------------

def test_analyse_stream_returns_sse_events(client):
    """POST /analyse-stream returns SSE events for pipeline steps."""
    guard_result = {"is_safe": True, "label": "safe", "raw_response": {}, "safety_flag": None}
    misinfo_result = {"misinformation_detected": False, "misinformation_type": "none", "claims": [], "explanation": "Clean"}
    insights_result = {"explanation": "No issues", "is_harmful": False, "llm_used": "gemini"}

    with patch("app.run_guard_detection", new_callable=AsyncMock, return_value=guard_result), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-stream",
            json={"text": "Test content for streaming analysis"},
        )

    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text

    # Verify SSE events are present
    assert "event: step" in body
    assert "event: result" in body
    assert '"id": "guard"' in body
    assert '"id": "misinfo"' in body
    assert '"id": "insights"' in body
    assert '"status": "running"' in body
    assert '"status": "done"' in body
    assert '"is_safe": true' in body


def test_analyse_stream_handles_guard_failure(client):
    """SSE endpoint handles GUARD failure gracefully."""
    misinfo_result = {"misinformation_detected": False, "misinformation_type": "none", "claims": [], "explanation": "Clean"}
    insights_result = {"explanation": "N/A", "is_harmful": False}

    with patch("app.run_guard_detection", new_callable=AsyncMock, side_effect=Exception("GUARD down")), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-stream",
            json={"text": "Test content"},
        )

    assert res.status_code == 200
    body = res.text
    # GUARD should fail but pipeline should continue
    assert "event: result" in body
    assert '"is_safe": null' in body


def test_analyse_stream_empty_text_returns_400(client):
    """SSE endpoint rejects empty text."""
    res = client.post("/analyse-stream", json={"text": ""})
    assert res.status_code == 400
    data = res.json()
    assert "error" in data


def test_analyse_stream_unsafe_content(client):
    """SSE endpoint detects unsafe content correctly."""
    guard_result = {"is_safe": False, "label": "unsafe", "raw_response": {}, "safety_flag": "hate_speech"}
    misinfo_result = {"misinformation_detected": True, "misinformation_type": "fabricated_quote", "claims": ["false claim"], "explanation": "Contains fabrication"}
    insights_result = {"explanation": "Issues found", "is_harmful": True, "llm_used": "gemini"}

    with patch("app.run_guard_detection", new_callable=AsyncMock, return_value=guard_result), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-stream",
            json={"text": "Harmful content here"},
        )

    assert res.status_code == 200
    body = res.text
    assert '"is_safe": false' in body


# ---------------------------------------------------------------------------
# Audio / Gemini Live API
# ---------------------------------------------------------------------------

def test_analyse_audio_success(client):
    """POST /analyse-audio returns base64 OGG audio on success."""
    fake_ogg = b"OggS" + b"\x00" * 100
    with patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=fake_ogg):
        res = client.post(
            "/analyse-audio",
            files={"file": ("test.webm", b"fake_audio_data", "audio/webm")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["mime_type"] == "audio/ogg"
    # Verify base64 decodes back to the OGG data
    decoded = base64.b64decode(data["audio"])
    assert decoded == fake_ogg


def test_analyse_audio_failure(client):
    """POST /analyse-audio returns success=False when Live API returns empty."""
    with patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=b""):
        res = client.post(
            "/analyse-audio",
            files={"file": ("test.webm", b"fake_audio_data", "audio/webm")},
        )
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is False


# ---------------------------------------------------------------------------
# WebSocket live audio
# ---------------------------------------------------------------------------

def test_websocket_live_audio_success(client):
    """WebSocket /ws/live-audio returns audio response."""
    fake_ogg = b"OggS" + b"\x00" * 50
    with patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=fake_ogg):
        with client.websocket_connect("/ws/live-audio") as ws:
            ws.send_bytes(b"fake_audio_data")
            ws.send_text("END")

            # First message: JSON with audio
            data = ws.receive_json()
            assert data["success"] is True
            assert data["audio"]

            # Second message: DONE signal
            done = ws.receive_text()
            assert done == "DONE"


def test_websocket_live_audio_no_data(client):
    """WebSocket returns error when no audio data sent."""
    with client.websocket_connect("/ws/live-audio") as ws:
        ws.send_text("END")

        data = ws.receive_json()
        assert "error" in data

        done = ws.receive_text()
        assert done == "DONE"


def test_websocket_live_audio_api_failure(client):
    """WebSocket returns success=False when Live API fails."""
    with patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=b""):
        with client.websocket_connect("/ws/live-audio") as ws:
            ws.send_bytes(b"fake_audio_data")
            ws.send_text("END")

            data = ws.receive_json()
            assert data["success"] is False

            done = ws.receive_text()
            assert done == "DONE"


# ---------------------------------------------------------------------------
# Image analysis SSE endpoint
# ---------------------------------------------------------------------------

def test_analyse_image_stream_returns_sse_events(client):
    """POST /analyse-image-stream returns SSE events for each pipeline step."""
    vis_result = {"caption": "A photo of a cat", "ocr_text": None, "ai_signals": "No AI signals"}
    guard_result = {"is_safe": True, "label": "safe", "raw_response": {}, "safety_flag": None}
    misinfo_result = {"misinformation_detected": False, "misinformation_type": "none", "claims": [], "explanation": "Clean"}
    manip_result = {"manipulation_detected": False, "manipulation_type": "none", "signals": [], "explanation": "No manipulation.", "confidence": 0.1}
    insights_result = {"explanation": "No issues found.", "is_harmful": False, "llm_used": "gemini"}

    with patch("app.analyse_image_with_gemini", new_callable=AsyncMock, return_value=vis_result), \
         patch("app.run_guard_detection", new_callable=AsyncMock, return_value=guard_result), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.detect_image_manipulation", new_callable=AsyncMock, return_value=manip_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-image-stream",
            files={"file": ("test.jpg", b"fake_image_data", "image/jpeg")},
        )

    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    body = res.text

    # All pipeline steps should appear
    assert "event: step" in body
    assert "event: result" in body
    assert '"id": "vision"' in body
    assert '"id": "guard"' in body
    assert '"id": "misinfo"' in body
    assert '"id": "manipulation"' in body
    assert '"id": "insights"' in body
    assert '"is_safe": true' in body


def test_analyse_image_stream_unsafe_content(client):
    """Image SSE endpoint detects unsafe content correctly."""
    vis_result = {"caption": "Manipulated photo", "ocr_text": "fake text", "ai_signals": "AI artifacts detected"}
    guard_result = {"is_safe": False, "label": "unsafe", "raw_response": {}, "safety_flag": "manipulation"}
    misinfo_result = {"misinformation_detected": True, "misinformation_type": "fabricated", "claims": ["fake"], "explanation": "Fabricated"}
    manip_result = {"manipulation_detected": True, "manipulation_type": "splicing", "signals": ["edge anomaly"], "explanation": "Splicing detected", "confidence": 0.9}
    insights_result = {"explanation": "Content is harmful.", "is_harmful": True, "llm_used": "gemini"}

    with patch("app.analyse_image_with_gemini", new_callable=AsyncMock, return_value=vis_result), \
         patch("app.run_guard_detection", new_callable=AsyncMock, return_value=guard_result), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.detect_image_manipulation", new_callable=AsyncMock, return_value=manip_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-image-stream",
            files={"file": ("test.jpg", b"fake_image", "image/jpeg")},
        )

    assert res.status_code == 200
    body = res.text
    assert '"is_safe": false' in body


def test_analyse_image_stream_handles_vision_failure(client):
    """Image SSE endpoint handles Gemini vision failure gracefully."""
    guard_result = {"is_safe": None, "label": "api_error", "raw_response": {}, "safety_flag": None}
    misinfo_result = {"misinformation_detected": False, "misinformation_type": "none", "claims": [], "explanation": "Clean"}
    manip_result = {"manipulation_detected": False, "manipulation_type": "none", "signals": [], "explanation": "OK", "confidence": 0.0}
    insights_result = {"explanation": "N/A", "is_harmful": False, "llm_used": "failed"}

    with patch("app.analyse_image_with_gemini", new_callable=AsyncMock, side_effect=Exception("Vision API down")), \
         patch("app.run_guard_detection", new_callable=AsyncMock, return_value=guard_result), \
         patch("app.detect_misinformation", new_callable=AsyncMock, return_value=misinfo_result), \
         patch("app.detect_image_manipulation", new_callable=AsyncMock, return_value=manip_result), \
         patch("app.run_insights", new_callable=AsyncMock, return_value=insights_result):
        res = client.post(
            "/analyse-image-stream",
            files={"file": ("test.jpg", b"fake_image", "image/jpeg")},
        )

    assert res.status_code == 200
    body = res.text
    # Vision error should not crash the pipeline
    assert "event: result" in body


# ---------------------------------------------------------------------------
# Enhanced audio with transcription + detection pipeline
# ---------------------------------------------------------------------------

def test_analyse_audio_includes_transcript(client):
    """POST /analyse-audio returns transcript and detection results alongside audio."""
    fake_ogg = b"OggS" + b"\x00" * 100
    transcript_result = {"transcript": "Hello world, test content.", "detected_language": "en"}
    detection_result = {
        "detection_result": {"is_safe": True, "label": "safe"},
        "misinfo_result": {"misinformation_detected": False},
        "insights_result": {"explanation": "Clean", "is_harmful": False},
        "is_safe": True,
        "misinfo_type": "none",
    }

    with patch("app.transcribe_audio", new_callable=AsyncMock, return_value=transcript_result), \
         patch("app.run_full_detection", new_callable=AsyncMock, return_value=detection_result), \
         patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=fake_ogg):
        res = client.post(
            "/analyse-audio",
            files={"file": ("test.webm", b"fake_audio_data", "audio/webm")},
        )

    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["transcript"] == "Hello world, test content."
    assert data["detected_language"] == "en"
    assert data["detection_result"]["is_safe"] is True


def test_analyse_audio_transcription_failure_still_returns(client):
    """Audio analysis continues even if transcription fails."""
    with patch("app.transcribe_audio", new_callable=AsyncMock, side_effect=Exception("Deepgram down")), \
         patch("app.live_voice_exchange", new_callable=AsyncMock, return_value=b""):
        res = client.post(
            "/analyse-audio",
            files={"file": ("test.webm", b"fake_audio", "audio/webm")},
        )

    assert res.status_code == 200
    data = res.json()
    # Should return with empty transcript, no crash
    assert data["transcript"] == ""
    assert data["success"] is False


# ---------------------------------------------------------------------------
# Research endpoint
# ---------------------------------------------------------------------------

def test_research_empty_query(client):
    """POST /research with empty query returns 400."""
    res = client.post("/research", json={"query": ""})
    assert res.status_code == 400
    assert "error" in res.json()


def test_research_success(client):
    """POST /research returns research summary and sources."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("## Research Summary\nThis is the summary.")
        tmp_path = f.name

    try:
        mock_result = {
            "summary_path": tmp_path,
            "skill_path": "",
            "cache_hit": False,
            "sources": ["https://example.com"],
            "raw_dir": "",
            "llm_used": "gemini",
        }
        with patch("research_agent.agent.research", new_callable=AsyncMock, return_value=mock_result):
            res = client.post("/research", json={"query": "fact check: coffee cures cancer"})

        assert res.status_code == 200
        data = res.json()
        assert "Research Summary" in data["summary"]
        assert data["sources"] == ["https://example.com"]
        assert data["llm_used"] == "gemini"
    finally:
        os.unlink(tmp_path)

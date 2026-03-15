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

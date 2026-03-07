"""Tests for media handler tool functions (mocked — no real API calls)."""

import asyncio
import sys
import os
import importlib.util
from unittest.mock import patch

# Import tools.py directly to avoid __init__.py triggering agent.py imports
_tools_path = os.path.join(os.path.dirname(__file__), '..', 'ai_agent_adk', 'tools.py')
_spec = importlib.util.spec_from_file_location('ai_agent_adk_tools_media', _tools_path)
_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tools)
analyse_image_with_gemini = _tools.analyse_image_with_gemini
transcribe_audio_deepgram = _tools.transcribe_audio_deepgram
synthesise_speech_elevenlabs = _tools.synthesise_speech_elevenlabs
analyse_video = _tools.analyse_video


def test_analyse_image_returns_structured_dict_on_error():
    """Image analysis returns error dict, never raises."""
    with patch.dict('os.environ', {'GEMINI_API_KEY': ''}):
        result = asyncio.run(analyse_image_with_gemini("/nonexistent/path.jpg"))
        assert "error" in result
        assert isinstance(result, dict)


def test_transcribe_audio_returns_structured_dict_on_error():
    """Audio transcription returns error dict, never raises."""
    with patch.dict('os.environ', {'DEEPGRAM_API_KEY': ''}):
        result = asyncio.run(transcribe_audio_deepgram("/nonexistent/audio.ogg"))
        assert "error" in result
        assert result["transcript"] == ""


def test_synthesise_speech_returns_structured_dict_on_error():
    """TTS returns error dict, never raises."""
    with patch.dict('os.environ', {'ELEVENLABS_API_KEY': ''}):
        result = asyncio.run(synthesise_speech_elevenlabs("Hello", "/tmp/test.mp3"))
        assert result["success"] is False
        assert "error" in result


def test_analyse_video_returns_structured_dict_on_error():
    """Video analysis returns error dict, never raises."""
    result = asyncio.run(analyse_video("/nonexistent/video.mp4"))
    assert "error" in result
    assert result["frames_checked"] == 0

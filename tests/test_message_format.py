"""Tests for the format_detection_response() function."""

import os
import importlib.util


# Import tools.py directly to avoid package-level side effects
_tools_path = os.path.join(os.path.dirname(__file__), '..', 'ai_agent_adk', 'tools.py')
_spec = importlib.util.spec_from_file_location('ai_agent_adk_tools_msgfmt', _tools_path)
_tools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tools)
format_detection_response = _tools.format_detection_response


def test_text_format_human_generated():
    result = format_detection_response(
        content_type="text",
        verdict="human-generated",
        is_ai_generated=False,
        confidence=0.82,
        explanation="Simple conversational query.",
    )
    assert "🟢" in result
    assert "Likely Human" in result or "Very Likely Human" in result
    assert "82%" in result
    assert "TEXT ANALYSIS" in result


def test_text_format_ai_generated():
    result = format_detection_response(
        content_type="text",
        verdict="ai-generated",
        is_ai_generated=True,
        confidence=0.95,
        explanation="Repetitive structure and generic phrasing.",
    )
    assert "🔴" in result
    assert "AI" in result and "Generated" in result


def test_image_format_includes_caption_and_ocr():
    result = format_detection_response(
        content_type="image",
        verdict="ai-generated",
        is_ai_generated=True,
        confidence=0.91,
        explanation="Smooth textures and inconsistent geometry.",
        caption="A woman with flowing hair",
        ocr_text="Hello World",
        ai_signals="Overly smooth skin",
    )
    assert "🖼️" in result
    assert "Image Content" in result
    assert "Detected Text" in result
    assert "Visual Signals" in result


def test_audio_format_includes_transcript():
    result = format_detection_response(
        content_type="audio",
        verdict="inconclusive",
        is_ai_generated=None,
        confidence=None,
        explanation="Cannot determine from transcript alone.",
        transcript="The government announced...",
    )
    assert "🎤" in result
    assert "Transcript" in result
    assert "Not available" in result


def test_video_format_includes_frames_and_transcript():
    result = format_detection_response(
        content_type="video",
        verdict="ai-generated",
        is_ai_generated=True,
        confidence=0.87,
        explanation="Frame inconsistencies detected.",
        frames_checked=5,
        transcript="Welcome to this tutorial...",
        ai_signals="Lip-sync issues",
    )
    assert "🎬" in result
    assert "Frames Analysed" in result
    assert "5" in result


def test_explanation_truncated_at_500_chars():
    long_text = "A" * 1000
    result = format_detection_response(
        content_type="text",
        verdict="test",
        is_ai_generated=None,
        confidence=None,
        explanation=long_text,
    )
    assert "..." in result
    assert len(result) < len(long_text) + 200


def test_footer_always_present():
    result = format_detection_response(
        content_type="text",
        verdict="test",
        is_ai_generated=None,
        confidence=None,
        explanation="Test.",
    )
    assert "SEA-LION GUARD" in result
    assert "automated analysis" in result
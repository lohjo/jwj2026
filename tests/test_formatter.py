"""Tests for pipeline/formatter.py — format_detection_message()."""

import pytest

from pipeline.formatter import format_detection_message


def test_outputs_valid_html():
    result = format_detection_message(
        content_type="text",
        verdict="unsafe",
        is_safe=False,
        explanation="This text contains misinformation.",
    )
    assert "<b>" in result
    assert "HTML" not in result or "parse_mode" not in result


def test_verdict_safe():
    result = format_detection_message(
        content_type="text",
        verdict="safe",
        is_safe=True,
        explanation="Looks genuine.",
    )
    assert "✅" in result
    assert "Safe" in result


def test_verdict_unsafe():
    result = format_detection_message(
        content_type="text",
        verdict="unsafe",
        is_safe=False,
        explanation="Contains false claims.",
    )
    assert "⚠️" in result
    assert "Unsafe" in result


def test_verdict_unsafe_plus_harmful():
    result = format_detection_message(
        content_type="text",
        verdict="unsafe",
        is_safe=False,
        explanation="Harmful content detected.",
        is_harmful=True,
    )
    assert "🚨" in result
    assert "Unsafe + Harmful" in result


def test_verdict_unclear():
    result = format_detection_message(
        content_type="text",
        verdict="Unknown",
        is_safe=None,
        explanation="Cannot determine.",
    )
    assert "❓" in result
    assert "Unclear" in result


def test_misinfo_type_displayed():
    result = format_detection_message(
        content_type="text",
        verdict="unsafe",
        is_safe=False,
        explanation="Fabricated quote detected.",
        misinfo_type="fabricated_quote",
    )
    assert "Fabricated Quote" in result
    assert "Type" in result


def test_misinfo_type_none_not_displayed():
    result = format_detection_message(
        content_type="text",
        verdict="safe",
        is_safe=True,
        explanation="All clear.",
        misinfo_type="none",
    )
    assert "Type" not in result


def test_no_confidence_bar():
    """Confidence bar should no longer appear in output."""
    result = format_detection_message(
        content_type="text",
        verdict="safe",
        is_safe=True,
        explanation="OK.",
    )
    assert "Confidence" not in result
    assert "█" not in result
    assert "░" not in result


def test_no_markdownv2_chars():
    """Ensure no raw MarkdownV2 special chars leak into the output format."""
    result = format_detection_message(
        content_type="text",
        verdict="test (special) - chars . ! #",
        is_safe=False,
        explanation="Test (with) - special . chars ! and # symbols",
    )
    assert "\\(" not in result
    assert "\\)" not in result
    assert "\\-" not in result
    assert "\\." not in result
    assert "\\!" not in result
    assert "\\#" not in result

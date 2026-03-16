"""Tests for config env parsing hardening."""

from config import _sanitize_env_value


def test_sanitize_env_value_strips_hash_comment() -> None:
    assert _sanitize_env_value("abc123 # your token") == "abc123"


def test_sanitize_env_value_strips_semicolon_comment() -> None:
    assert _sanitize_env_value("abc123 ; your token") == "abc123"


def test_sanitize_env_value_preserves_internal_symbols() -> None:
    assert _sanitize_env_value("abc#123") == "abc#123"
    assert _sanitize_env_value("abc;123") == "abc;123"


def test_sanitize_env_value_default_on_empty_or_none() -> None:
    assert _sanitize_env_value(None, "fallback") == "fallback"
    assert _sanitize_env_value("   ", "fallback") == "fallback"


def test_sanitize_env_value_strips_utf8_bom_prefix() -> None:
    assert _sanitize_env_value("\ufeffabc123") == "abc123"

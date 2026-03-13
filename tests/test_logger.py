"""Tests for pipeline/logger.py — log_to_clickhouse()."""

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_ch_client():
    """Reset the module-level ClickHouse client between tests."""
    import pipeline.logger as mod
    mod._ch_client = None
    yield
    mod._ch_client = None


def test_never_raises_on_clickhouse_exception():
    with patch("pipeline.logger._get_ch_client") as mock_get:
        mock_client = MagicMock()
        mock_client.insert.side_effect = RuntimeError("ClickHouse down")
        mock_get.return_value = mock_client

        from pipeline.logger import log_to_clickhouse
        # Should not raise
        result = log_to_clickhouse({"user_id": "test"})
        assert result["status"] == "failed"


def test_async_insert_settings():
    with patch("pipeline.logger._get_ch_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client

        from pipeline.logger import log_to_clickhouse
        log_to_clickhouse({"user_id": "test"})

        call_args = mock_client.insert.call_args
        settings = call_args.kwargs.get("settings", {})
        assert settings.get("async_insert") == 1
        assert settings.get("wait_for_async_insert") == 0


def test_logs_model_versions_field():
    with patch("pipeline.logger._get_ch_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client

        from pipeline.logger import log_to_clickhouse
        log_to_clickhouse({
            "user_id": "test",
            "model_versions": {"llm_used": "gemini"},
        })

        call_args = mock_client.insert.call_args
        # The row data should contain model_versions map
        row = call_args.args[1][0]  # First row
        # model_versions is at index 15 in the columns list
        assert isinstance(row[15], dict)


def test_swallows_errors_to_stderr(capsys):
    with patch("pipeline.logger._get_ch_client") as mock_get:
        mock_client = MagicMock()
        mock_client.insert.side_effect = ConnectionError("connection lost")
        mock_get.return_value = mock_client

        from pipeline.logger import log_to_clickhouse
        result = log_to_clickhouse({"user_id": "test"})
        assert result["status"] == "failed"
        # Error should be printed to stderr
        captured = capsys.readouterr()
        assert "log_to_clickhouse failed" in captured.err


def test_returns_failed_when_no_client():
    with patch("pipeline.logger._get_ch_client", return_value=None):
        from pipeline.logger import log_to_clickhouse
        result = log_to_clickhouse({"user_id": "test"})
        assert result["status"] == "failed"
        assert "unavailable" in result["error"].lower()

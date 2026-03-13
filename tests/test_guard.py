"""Tests for pipeline/guard.py — run_guard_detection()."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


@pytest.fixture(autouse=True)
def _reset_guard_client():
    """Reset the module-level HTTP client between tests."""
    import pipeline.guard as g
    g._http_client = None
    yield
    g._http_client = None


def _mock_response(text: str, status: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = {
        "choices": [{"message": {"content": text}}]
    }
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.mark.asyncio
async def test_correct_dict_shape_on_success():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response(
            "Label: safe content\nThis is safe."
        )
        mock_client.return_value = client

        result = await asyncio.wait_for(
            __import__("pipeline.guard", fromlist=["run_guard_detection"]).run_guard_detection("test text"),
            timeout=5,
        )
        assert "is_safe" in result
        assert "label" in result
        assert "raw_response" in result
        assert "safety_flag" in result


@pytest.mark.asyncio
async def test_api_error_label_on_http_500():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response("error", status=500)
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("test text")
        assert result["label"] == "api_error"


@pytest.mark.asyncio
async def test_auth_error_label_on_http_401():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response("unauthorized", status=401)
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("test text")
        assert result["label"] == "auth_error"


@pytest.mark.asyncio
async def test_permission_denied_label_on_http_403():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response("forbidden", status=403)
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("test text")
        assert result["label"] == "permission_denied"


@pytest.mark.asyncio
async def test_timeout_label():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.side_effect = asyncio.TimeoutError()
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("test text", timeout=0.1)
        assert result["label"] == "timeout"


@pytest.mark.asyncio
async def test_api_key_missing():
    with patch("pipeline.guard.SEALION_API_KEY", ""):
        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("test text")
        assert result["label"] == "api_key_missing"


@pytest.mark.asyncio
async def test_detects_unsafe_content():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response(
            "This content is unsafe. It contains harmful material."
        )
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("some text")
        assert result["is_safe"] is False
        assert result["safety_flag"] == "unsafe"


@pytest.mark.asyncio
async def test_detects_safe_content():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response(
            "This content appears to be safe and genuine."
        )
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("some text")
        assert result["is_safe"] is True
        assert result["safety_flag"] is None


@pytest.mark.asyncio
async def test_error_returns_none_is_safe():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response("error", status=500)
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("some text")
        assert result["is_safe"] is None


@pytest.mark.asyncio
async def test_handles_unrecognised_format():
    with patch("pipeline.guard._get_http_client") as mock_client:
        client = AsyncMock()
        client.post.return_value = _mock_response("Something unexpected format")
        mock_client.return_value = client

        from pipeline.guard import run_guard_detection
        result = await run_guard_detection("some text")
        assert isinstance(result, dict)
        assert "label" in result


@pytest.mark.asyncio
async def test_invalid_input():
    from pipeline.guard import run_guard_detection
    result = await run_guard_detection("")
    assert result["label"] == "invalid_input"

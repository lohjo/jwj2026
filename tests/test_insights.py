"""Tests for pipeline/insights.py — call_llm()."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_returns_gemini_response_on_success():
    mock_response = MagicMock()
    mock_response.text = "Gemini response text"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GEMINI_API_KEY", "test-gemini-key"):
        mock_genai.Client.return_value = mock_client

        from pipeline.insights import call_llm
        text, llm_used = await call_llm("test prompt")
        assert text == "Gemini response text"
        assert llm_used == "gemini"


@pytest.mark.asyncio
async def test_falls_back_to_vertex_on_gemini_exception():
    mock_primary_client = MagicMock()
    mock_primary_client.models.generate_content.side_effect = RuntimeError("Gemini down")

    mock_vertex_response = MagicMock()
    mock_vertex_response.text = "Vertex response"
    mock_vertex_client = MagicMock()
    mock_vertex_client.models.generate_content.return_value = mock_vertex_response

    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GOOGLE_CLOUD_PROJECT", "test-project"):
        mock_genai.Client.side_effect = [mock_primary_client, mock_vertex_client]

        from pipeline.insights import call_llm
        text, llm_used = await call_llm("test prompt")
        assert text == "Vertex response"
        assert llm_used == "vertex"


@pytest.mark.asyncio
async def test_returns_empty_when_both_fail():
    mock_primary_client = MagicMock()
    mock_primary_client.models.generate_content.side_effect = RuntimeError("Gemini down")
    mock_vertex_client = MagicMock()
    mock_vertex_client.models.generate_content.side_effect = RuntimeError("Vertex down")

    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GOOGLE_CLOUD_PROJECT", "test-project"):
        mock_genai.Client.side_effect = [mock_primary_client, mock_vertex_client]

        from pipeline.insights import call_llm
        text, llm_used = await call_llm("test prompt")
        assert text == ""
        assert llm_used == "failed"


@pytest.mark.asyncio
async def test_returns_empty_when_vertex_location_missing():
    mock_primary_client = MagicMock()
    mock_primary_client.models.generate_content.side_effect = RuntimeError("Gemini down")

    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GOOGLE_CLOUD_PROJECT", "test-project"), \
         patch("pipeline.insights.GOOGLE_CLOUD_LOCATION", ""):
        mock_genai.Client.return_value = mock_primary_client

        from pipeline.insights import call_llm
        text, llm_used = await call_llm("test prompt")
        assert text == ""
        assert llm_used == "failed"


@pytest.mark.asyncio
async def test_never_raises():
    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GOOGLE_CLOUD_PROJECT", "test-project"):
        mock_genai.Client.side_effect = Exception("unexpected")

        from pipeline.insights import call_llm
        # Should not raise
        text, llm_used = await call_llm("test prompt")
        assert isinstance(text, str)
        assert llm_used == "failed"


@pytest.mark.asyncio
async def test_llm_used_gemini_value():
    mock_response = MagicMock()
    mock_response.text = "OK"

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response

    with patch("pipeline.insights.genai") as mock_genai, \
         patch("pipeline.insights.GEMINI_API_KEY", "test-gemini-key"):
        mock_genai.Client.return_value = mock_client

        from pipeline.insights import call_llm
        _, llm_used = await call_llm("test")
        assert llm_used == "gemini"

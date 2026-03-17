"""Tests for research_agent — crawler.scrape_url() and agent.research()."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestScrapeUrl:
    @pytest.mark.asyncio
    async def test_returns_failure_on_http_error(self):
        with patch("research_agent.crawler.FIRECRAWL_API_KEY", "fake-key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status.side_effect = Exception("HTTP 500")
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            from research_agent.crawler import scrape_url
            result = await scrape_url("https://example.com")
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_filters_low_word_count(self):
        with patch("research_agent.crawler.FIRECRAWL_API_KEY", "fake-key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "data": {
                    "markdown": "short text",
                    "metadata": {"title": "Test"},
                }
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            from research_agent.crawler import scrape_url
            result = await scrape_url("https://example.com")
            assert result["success"] is False  # word_count < 150

    @pytest.mark.asyncio
    async def test_uses_only_main_content(self):
        with patch("research_agent.crawler.FIRECRAWL_API_KEY", "fake-key"), \
             patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = {
                "data": {
                    "markdown": " ".join(["word"] * 200),
                    "metadata": {"title": "Test"},
                }
            }
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            from research_agent.crawler import scrape_url
            await scrape_url("https://example.com")

            # Verify onlyMainContent was in the request body
            call_args = mock_client.post.call_args
            body = call_args.kwargs.get("json", {})
            assert body.get("onlyMainContent") is True


class TestResearch:
    @pytest.mark.asyncio
    async def test_uses_skill_cache_when_hit(self, tmp_path):
        from research_agent.skill_cache import SkillEntry
        cached = SkillEntry(
            path=str(tmp_path / "cached.md"),
            topic="test topic",
            last_updated="2025-01-01",
            confidence="high",
            sources=["https://example.com"],
            content="# Cached",
        )

        with patch("research_agent.agent.skill_cache") as mock_cache:
            mock_cache.lookup.return_value = (cached, 0.90)

            from research_agent.agent import research
            result = await research("test topic")
            assert result["cache_hit"] is True
            assert result["skill_path"] == str(tmp_path / "cached.md")

    @pytest.mark.asyncio
    async def test_writes_summary_md(self, tmp_path):
        pages = [
            {"url": "https://example.com", "title": "Test", "markdown": " ".join(["word"] * 200), "word_count": 200, "success": True}
        ]

        with patch("research_agent.agent.skill_cache") as mock_cache, \
             patch("research_agent.agent.FIRECRAWL_API_KEY", "fake-key"), \
             patch("research_agent.agent.search_and_scrape", new_callable=AsyncMock, return_value=pages), \
             patch("research_agent.agent.summarise", new_callable=AsyncMock) as mock_sum, \
             patch("research_agent.agent.SUMMARIES_DIR", tmp_path / "summaries"), \
             patch("research_agent.agent.SKILLS_DIR", tmp_path / "skills"), \
             patch("research_agent.agent.RAW_DIR", tmp_path / "raw"):
            mock_cache.lookup.return_value = (None, 0.0)
            mock_sum.return_value = {
                "summary_md": "# Summary",
                "skill_md": "# Skill",
                "sources": ["https://example.com"],
                "llm_used": "gemini",
            }

            (tmp_path / "summaries").mkdir()
            (tmp_path / "skills").mkdir()
            (tmp_path / "raw").mkdir()

            from research_agent.agent import research
            result = await research("test query")

            assert result["summary_path"]
            assert Path(result["summary_path"]).exists()
            assert Path(result["summary_path"]).read_text(encoding="utf-8") == "# Summary"

    @pytest.mark.asyncio
    async def test_writes_skill_card(self, tmp_path):
        pages = [
            {"url": "https://example.com", "title": "Test", "markdown": " ".join(["word"] * 200), "word_count": 200, "success": True}
        ]

        with patch("research_agent.agent.skill_cache") as mock_cache, \
             patch("research_agent.agent.FIRECRAWL_API_KEY", "fake-key"), \
             patch("research_agent.agent.search_and_scrape", new_callable=AsyncMock, return_value=pages), \
             patch("research_agent.agent.summarise", new_callable=AsyncMock) as mock_sum, \
             patch("research_agent.agent.SUMMARIES_DIR", tmp_path / "summaries"), \
             patch("research_agent.agent.SKILLS_DIR", tmp_path / "skills"), \
             patch("research_agent.agent.RAW_DIR", tmp_path / "raw"):
            mock_cache.lookup.return_value = (None, 0.0)
            mock_sum.return_value = {
                "summary_md": "# Summary",
                "skill_md": "# Skill Card",
                "sources": ["https://example.com"],
                "llm_used": "groq",
            }

            (tmp_path / "summaries").mkdir()
            (tmp_path / "skills").mkdir()
            (tmp_path / "raw").mkdir()

            from research_agent.agent import research
            result = await research("test query")

            assert result["skill_path"]
            assert Path(result["skill_path"]).exists()
            assert "Skill Card" in Path(result["skill_path"]).read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_creates_raw_dir(self, tmp_path):
        pages = [
            {"url": "https://example.com", "title": "T", "markdown": " ".join(["w"] * 200), "word_count": 200, "success": True}
        ]

        with patch("research_agent.agent.skill_cache") as mock_cache, \
             patch("research_agent.agent.FIRECRAWL_API_KEY", "fake-key"), \
             patch("research_agent.agent.search_and_scrape", new_callable=AsyncMock, return_value=pages), \
             patch("research_agent.agent.summarise", new_callable=AsyncMock) as mock_sum, \
             patch("research_agent.agent.SUMMARIES_DIR", tmp_path / "summaries"), \
             patch("research_agent.agent.SKILLS_DIR", tmp_path / "skills"), \
             patch("research_agent.agent.RAW_DIR", tmp_path / "raw"):
            mock_cache.lookup.return_value = (None, 0.0)
            mock_sum.return_value = {
                "summary_md": "# S", "skill_md": "# K",
                "sources": ["https://example.com"], "llm_used": "gemini",
            }

            (tmp_path / "summaries").mkdir()
            (tmp_path / "skills").mkdir()
            (tmp_path / "raw").mkdir()

            from research_agent.agent import research
            result = await research("test query")

            assert result["raw_dir"]
            raw_dir = Path(result["raw_dir"])
            assert raw_dir.exists()
            assert (raw_dir / "metadata.json").exists()

    @pytest.mark.asyncio
    async def test_cache_hit_true(self, tmp_path):
        from research_agent.skill_cache import SkillEntry
        cached = SkillEntry(
            path="skill.md", topic="topic", last_updated="2025-01-01",
            confidence="high", sources=["url"], content="content",
        )

        with patch("research_agent.agent.skill_cache") as mock_cache:
            mock_cache.lookup.return_value = (cached, 0.85)

            from research_agent.agent import research
            result = await research("topic")
            assert result["cache_hit"] is True

    @pytest.mark.asyncio
    async def test_returns_error_when_firecrawl_key_missing(self):
        with patch("research_agent.agent.FIRECRAWL_API_KEY", ""), \
             patch("research_agent.agent.skill_cache") as mock_cache:
            mock_cache.lookup.return_value = (None, 0.0)

            from research_agent.agent import research
            result = await research("fact check: test")

            assert result["llm_used"] == "failed"
            assert result["error"].startswith("Research unavailable:")

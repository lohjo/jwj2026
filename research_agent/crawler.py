"""
research_agent/crawler.py — Firecrawl API wrapper.

Replaces the old httpx + trafilatura fetcher with Firecrawl's
/scrape and /search endpoints for clean markdown output.
"""

import logging

import httpx

from config import FIRECRAWL_API_KEY

logger = logging.getLogger(__name__)

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"


async def scrape_url(url: str) -> dict:
    """
    Scrape a single URL using Firecrawl /scrape endpoint.

    Returns:
        dict: url (str), title (str), markdown (str),
              word_count (int), success (bool).
    """
    _fail = {
        "url": url,
        "title": "",
        "markdown": "",
        "word_count": 0,
        "success": False,
    }

    if not FIRECRAWL_API_KEY:
        logger.warning("[Crawler] FIRECRAWL_API_KEY not set")
        return _fail

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{FIRECRAWL_BASE}/scrape",
                headers={
                    "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            page_data = data.get("data", {})
            markdown = page_data.get("markdown", "")
            title = page_data.get("metadata", {}).get("title", "")
            word_count = len(markdown.split())

            if word_count < 150:
                logger.debug("[Crawler] Skipping %s — only %d words", url, word_count)
                return _fail

            return {
                "url": url,
                "title": title,
                "markdown": markdown,
                "word_count": word_count,
                "success": True,
            }
    except Exception as e:
        logger.warning("[Crawler] Scrape failed for %s: %s", url, e)
        return _fail


async def search_and_scrape(query: str, num_results: int = 6) -> list[dict]:
    """
    Use Firecrawl /search endpoint to find + scrape top results in one call.

    Returns list of scrape dicts filtered to word_count >= 150.
    """
    if not FIRECRAWL_API_KEY:
        logger.warning("[Crawler] FIRECRAWL_API_KEY not set")
        return []

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{FIRECRAWL_BASE}/search",
                headers={
                    "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "limit": num_results,
                    "scrapeOptions": {
                        "formats": ["markdown"],
                        "onlyMainContent": True,
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("data", []):
                markdown = item.get("markdown", "")
                word_count = len(markdown.split())
                if word_count < 150:
                    continue
                results.append({
                    "url": item.get("url", ""),
                    "title": item.get("metadata", {}).get("title", ""),
                    "markdown": markdown,
                    "word_count": word_count,
                    "success": True,
                })

            return results
    except Exception as e:
        logger.warning("[Crawler] Search failed: %s", e)
        return []

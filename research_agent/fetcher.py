"""Fetch and extract clean text from web pages."""

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

MAX_PAGE_BYTES = 50 * 1024  # 50 KB cap per page
FETCH_TIMEOUT = 15.0


@dataclass
class FetchedPage:
    url: str
    domain: str
    text: str
    word_count: int


async def fetch_and_extract(url: str, client: httpx.AsyncClient) -> FetchedPage | None:
    """
    Fetch a URL and extract clean text using trafilatura.

    Returns None if the page cannot be fetched or has < 200 words.
    """
    try:
        resp = await asyncio.wait_for(
            client.get(url, follow_redirects=True),
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        raw_html = resp.text[:MAX_PAGE_BYTES]
    except Exception as exc:
        logger.debug("Fetch failed for %s: %s", url, exc)
        return None

    try:
        import trafilatura
        text = trafilatura.extract(raw_html) or ""
    except Exception:
        text = ""

    word_count = len(text.split())
    if word_count < 200:
        logger.debug("Skipping %s — only %d words", url, word_count)
        return None

    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    return FetchedPage(url=url, domain=domain, text=text, word_count=word_count)


async def fetch_all(urls: list[str]) -> list[FetchedPage]:
    """Fetch and extract text from a list of URLs concurrently."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT),
        limits=httpx.Limits(max_connections=10),
        headers={"User-Agent": "SENTINEL-ResearchAgent/1.0"},
    ) as client:
        tasks = [fetch_and_extract(u, client) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    return [r for r in results if isinstance(r, FetchedPage)]

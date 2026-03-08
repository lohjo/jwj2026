"""
research_agent.agent — Main entrypoint for the web research subagent.

Usage:
    from research_agent import research
    result = await research("How does SEA-LION GUARD score text?")
"""

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Output directories (relative to project root)
RAW_DIR = Path("research/raw")
SUMMARIES_DIR = Path("research/summaries")
SKILLS_DIR = Path("research/skills")


@dataclass
class ResearchResult:
    summary_path: str
    skill_path: str
    cache_hit: bool
    sources: list[str]
    raw_dir: str


def _slugify(text: str, max_len: int = 40) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '_', text.lower()).strip('_')
    return slug[:max_len]


async def _searxng_search(query: str, num_results: int = 10) -> list[str]:
    """Search the web via SearXNG and return a list of result URLs."""
    import httpx

    searxng_url = os.getenv("SEARXNG_URL", "http://localhost:8080")
    params = {
        "q": query,
        "format": "json",
        "safesearch": 1,
        "pageno": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{searxng_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            return [r["url"] for r in results[:num_results] if r.get("url")]
    except Exception as exc:
        logger.warning("SearXNG search failed: %s", exc)
        return []


async def research(query: str, force_refresh: bool = False) -> ResearchResult:
    """
    Main entrypoint for web research.

    Args:
        query: Natural language research question.
        force_refresh: Skip skill cache even if hit found.

    Returns:
        ResearchResult with paths to summary, skill card, and raw data.
    """
    from research_agent import skill_cache, fetcher, deduplicator, summariser

    # Ensure output dirs exist
    for d in (RAW_DIR, SUMMARIES_DIR, SKILLS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    date_prefix = datetime.now().strftime("%Y%m%d")
    slug = _slugify(query)
    folder_name = f"{date_prefix}_{slug}"

    # ── Step 1: Check skill cache ──────────────────────────────────────────
    if not force_refresh:
        cached_skill, similarity = await asyncio.to_thread(skill_cache.lookup, query)

        if cached_skill and similarity > 0.80:
            logger.info("Skill cache HIT (sim=%.2f) for '%s'", similarity, query)
            return ResearchResult(
                summary_path="",
                skill_path=cached_skill.path,
                cache_hit=True,
                sources=cached_skill.sources,
                raw_dir="",
            )

        if cached_skill and similarity > 0.60:
            logger.info("Skill cache PARTIAL (sim=%.2f) — targeted update search", similarity)
            # Targeted: add "latest" / "update" to query for fresh results
            query = f"{query} latest update"

    # ── Step 2: Search the web ─────────────────────────────────────────────
    urls = await _searxng_search(query)
    if not urls:
        logger.warning("No search results for '%s'", query)
        return ResearchResult(
            summary_path="",
            skill_path="",
            cache_hit=False,
            sources=[],
            raw_dir="",
        )

    # ── Step 3: Fetch and extract ──────────────────────────────────────────
    pages = await fetcher.fetch_all(urls)
    if not pages:
        logger.warning("No pages extracted for '%s'", query)
        return ResearchResult(
            summary_path="", skill_path="", cache_hit=False,
            sources=urls, raw_dir="",
        )

    # ── Step 4: Deduplicate ────────────────────────────────────────────────
    unique_pages = await asyncio.to_thread(deduplicator.deduplicate, pages)
    logger.info("Dedup: %d → %d pages", len(pages), len(unique_pages))

    # ── Step 5: Save raw data ──────────────────────────────────────────────
    raw_subdir = RAW_DIR / folder_name
    raw_subdir.mkdir(parents=True, exist_ok=True)

    metadata = []
    for i, page in enumerate(unique_pages, 1):
        fname = f"{i:02d}_{_slugify(page.domain, 30)}.txt"
        (raw_subdir / fname).write_text(page.text, encoding="utf-8")
        metadata.append({
            "index": i,
            "url": page.url,
            "domain": page.domain,
            "word_count": page.word_count,
            "fetched_at": datetime.now().isoformat(),
        })

    (raw_subdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # ── Step 6: Summarise ──────────────────────────────────────────────────
    source_urls = [p.url for p in unique_pages]
    summary_text = await summariser.summarise_pages(query, unique_pages)
    summary_path = SUMMARIES_DIR / f"{folder_name}.md"
    summary_path.write_text(summary_text, encoding="utf-8")

    # ── Step 7: Generate skill card ────────────────────────────────────────
    skill_text = await summariser.generate_skill_card(query, summary_text, source_urls)
    skill_path = SKILLS_DIR / f"{slug}.md"
    skill_path.write_text(skill_text, encoding="utf-8")

    return ResearchResult(
        summary_path=str(summary_path),
        skill_path=str(skill_path),
        cache_hit=False,
        sources=source_urls,
        raw_dir=str(raw_subdir),
    )

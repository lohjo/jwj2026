"""
research_agent/agent.py — Main entrypoint for the web research subagent.

Usage:
    from research_agent.agent import research
    result = await research("How does SEA-LION GUARD score text?")
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

from config import RESEARCH_DIR
from research_agent.crawler import search_and_scrape
from research_agent.summariser import summarise
from research_agent import skill_cache

logger = logging.getLogger(__name__)

RAW_DIR = RESEARCH_DIR / "raw"
SUMMARIES_DIR = RESEARCH_DIR / "summaries"
SKILLS_DIR = RESEARCH_DIR / "skills"


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len]


async def research(query: str, force_refresh: bool = False) -> dict:
    """
    Main entrypoint for web research.

    Returns:
        {
          "summary_path": str,
          "skill_path": str,
          "cache_hit": bool,
          "sources": list[str],
          "raw_dir": str,
          "llm_used": str
        }
    """
    for d in (RAW_DIR, SUMMARIES_DIR, SKILLS_DIR):
        d.mkdir(parents=True, exist_ok=True)

    date_prefix = datetime.now().strftime("%Y%m%d")
    slug = _slugify(query)
    folder_name = f"{date_prefix}_{slug}"

    # ── Step 1: Check skill cache ──
    if not force_refresh:
        cached_skill, similarity = await asyncio.to_thread(skill_cache.lookup, query)
        if cached_skill and similarity > 0.80:
            logger.info("Skill cache HIT (sim=%.2f) for '%s'", similarity, query)
            return {
                "summary_path": "",
                "skill_path": cached_skill.path,
                "cache_hit": True,
                "sources": cached_skill.sources,
                "raw_dir": "",
                "llm_used": "",
            }

    # ── Step 2: Search + scrape via Firecrawl ──
    pages = await search_and_scrape(query, num_results=6)
    if not pages:
        logger.warning("No search results for '%s'", query)
        return {
            "summary_path": "",
            "skill_path": "",
            "cache_hit": False,
            "sources": [],
            "raw_dir": "",
            "llm_used": "failed",
        }

    # ── Step 3: Save raw scraped content ──
    raw_subdir = RAW_DIR / folder_name
    raw_subdir.mkdir(parents=True, exist_ok=True)

    metadata = []
    for i, page in enumerate(pages, 1):
        domain = ""
        try:
            from urllib.parse import urlparse
            domain = urlparse(page["url"]).netloc
        except Exception:
            pass
        fname = f"{i:02d}_{_slugify(domain, 30)}.txt"
        (raw_subdir / fname).write_text(page["markdown"][:5000], encoding="utf-8")
        metadata.append({
            "index": i,
            "url": page["url"],
            "domain": domain,
            "word_count": page["word_count"],
            "fetched_at": datetime.now().isoformat(),
        })

    (raw_subdir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    # ── Step 4: Summarise via LLM ──
    result = await summarise(query, pages)

    summary_path = SUMMARIES_DIR / f"{folder_name}.md"
    summary_path.write_text(result["summary_md"], encoding="utf-8")

    skill_path = SKILLS_DIR / f"{slug}.md"
    skill_path.write_text(result["skill_md"], encoding="utf-8")

    return {
        "summary_path": str(summary_path),
        "skill_path": str(skill_path),
        "cache_hit": False,
        "sources": result["sources"],
        "raw_dir": str(raw_subdir),
        "llm_used": result["llm_used"],
    }

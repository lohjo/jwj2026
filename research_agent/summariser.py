"""
research_agent/summariser.py — LLM summarisation via call_llm().

All LLM calls go through pipeline.insights.call_llm() (Gemini → Groq fallback).
"""

import json
import logging
import re
from datetime import date

from pipeline.insights import call_llm

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """
You are a research analyst. Summarise the following web content into two documents.

Query: {query}

Sources:
{sources_text}

Respond ONLY with a JSON object (no markdown fences):
{{
  "summary_md": "# {query}\\n\\n## Overview\\n...\\n\\n## Key Findings\\n...\\n\\n## Sources\\n...",
  "skill_md": "---\\ntopic: {topic_slug}\\nlast_updated: {today}\\nsources: [{source_list}]\\nconfidence: high|medium|low\\n---\\n\\n# {query}\\n\\n## Key Facts\\n- ...\\n\\n## Code Patterns\\n```\\n# if applicable\\n```\\n\\n## Gotchas\\n- ...\\n\\n## Do Not Search Again If\\n- ..."
}}

Rules:
- summary_md is for humans: clear prose, headers, bullet points
- skill_md is for the AI model: facts only, no filler, include working code if relevant
- Both must directly answer the query using the sources provided
- Do not invent facts not present in the sources
"""


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len]


async def summarise(query: str, scraped_pages: list[dict]) -> dict:
    """
    Produce structured summary from scraped pages.

    Args:
        query: Original research query.
        scraped_pages: List of dicts from crawler.search_and_scrape().

    Returns:
        {
          "summary_md": str,
          "skill_md": str,
          "sources": list[str],
          "llm_used": str
        }
    """
    sources = [p["url"] for p in scraped_pages if p.get("url")]
    source_list = ", ".join(sources[:5])
    today = date.today().isoformat()
    topic_slug = _slugify(query)

    sources_text = "\n\n---\n\n".join(
        f"Source: {p['url']}\nTitle: {p.get('title', '')}\n{p['markdown'][:3000]}"
        for p in scraped_pages[:8]
    )

    prompt = SUMMARY_PROMPT.format(
        query=query,
        sources_text=sources_text,
        topic_slug=topic_slug,
        today=today,
        source_list=source_list,
    )

    raw, llm_used = await call_llm(prompt, max_tokens=2048)

    if raw:
        try:
            clean = re.sub(
                r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE
            ).strip()
            parsed = json.loads(clean)
            return {
                "summary_md": parsed.get("summary_md", ""),
                "skill_md": parsed.get("skill_md", ""),
                "sources": sources,
                "llm_used": llm_used,
            }
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("[Summariser] JSON parse failed, using raw response: %s", e)
            return {
                "summary_md": raw,
                "skill_md": "",
                "sources": sources,
                "llm_used": llm_used,
            }

    # Total failure
    return {
        "summary_md": f"# Research Summary\n\nSummarisation failed for query: {query}",
        "skill_md": f"---\ntopic: {topic_slug}\nlast_updated: {today}\nsources: [{source_list}]\nconfidence: low\n---\n\n# {query}\n\n## Key Facts\n- Summarisation failed — see raw sources",
        "sources": sources,
        "llm_used": llm_used,
    }

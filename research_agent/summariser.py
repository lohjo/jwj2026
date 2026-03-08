"""Summarise research sources and generate skill cards."""

import asyncio
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def _call_gemini(prompt: str) -> str | None:
    """Synchronous Gemini call (run via asyncio.to_thread)."""
    try:
        import google.genai as genai

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            logger.warning("[Summariser] GEMINI_API_KEY not set")
            return None

        client = genai.Client(api_key=api_key)
        model = os.getenv("MODEL_NAME", "gemini-2.5-flash")
        resp = client.models.generate_content(model=model, contents=prompt)
        return resp.text
    except Exception:
        logger.exception("[Summariser] Gemini call failed")
        return None


async def summarise_pages(query: str, pages) -> str:
    """
    Produce a structured Markdown summary from deduplicated pages.

    Args:
        query: The original research question.
        pages: List of FetchedPage objects.

    Returns:
        Markdown summary string.
    """
    combined = "\n\n---\n\n".join(
        f"Source: {p.url}\n{p.text[:3000]}" for p in pages[:8]
    )

    prompt = f"""You are a research assistant. Summarise the following web sources 
into a structured Markdown document answering the question: "{query}"

Sources:
{combined}

Output format:
# Research Summary: {{topic}}

## Key Findings
- Bullet points of most important facts

## Details
Comprehensive paragraph-form summary

## Sources
- Numbered list of source URLs used

Rules:
- Be factual and concise
- Cite which source each finding comes from
- If sources conflict, note the disagreement
- Do not fabricate information beyond what the sources provide"""

    result = await asyncio.to_thread(_call_gemini, prompt)
    return result or f"# Research Summary\n\nSummarisation failed for query: {query}"


async def generate_skill_card(query: str, summary: str, sources: list[str]) -> str:
    """
    Generate a model-facing skill card from a summary.

    Args:
        query: The original research question.
        summary: The Markdown summary text.
        sources: List of source URLs.

    Returns:
        Skill card Markdown string.
    """
    source_list = ", ".join(sources[:5])
    today = date.today().isoformat()

    prompt = f"""Convert this research summary into a concise skill card for an AI agent.

Summary:
{summary[:4000]}

Use this exact template:

---
topic: {{topic derived from the query}}
last_updated: {today}
sources: [{source_list}]
confidence: high | medium | low
---

# {{Topic Title}}

## Key Facts
- Bullet-point distilled facts only — no filler prose

## Code Patterns
```
# Minimal working example if applicable (omit if not relevant)
```

## Gotchas
- Known failure modes, edge cases, version-specific behaviour

## Do Not Search Again If
- Conditions under which this skill is sufficient

Rules:
- Keep it under 500 words
- Only include verified facts from the summary
- Set confidence based on source quality and agreement"""

    result = await asyncio.to_thread(_call_gemini, prompt)
    if result:
        return result

    # Fallback: minimal skill card
    return f"""---
topic: {query}
last_updated: {today}
sources: [{source_list}]
confidence: low
---

# {query}

## Key Facts
- Auto-generated skill card — summarisation failed
- See raw sources for details

## Gotchas
- Skill card was not AI-summarised; review raw data

## Do Not Search Again If
- Never — always re-search until a proper skill card is generated
"""

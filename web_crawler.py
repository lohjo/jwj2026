"""
Web crawler that integrates with research_agent to fetch, deduplicate, and
flag AI-generated content, saving results into a .md report.

Pipeline:
  1. Search via research_agent._searxng_search (or accept explicit URLs)
  2. Fetch & extract via research_agent.fetcher.fetch_all
  3. Deduplicate via research_agent.deduplicator.deduplicate
  4. Run AI detection (GUARD + misinformation) on each page
  5. Save flagged content to crawl_results/<timestamp>_<slug>.md
"""

import asyncio
import datetime
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

CRAWL_DIR = Path(__file__).resolve().parent / "crawl_results"
MAX_PAGES = 10


async def _detect_ai(content: str) -> dict:
    """Run GUARD + misinformation detection on content. Returns result dict."""
    from ai_agent_adk.tools import run_guard_detection, detect_misinformation

    guard_result = {}
    misinfo_result = {}

    gathered = await asyncio.gather(
        run_guard_detection(content[:2000], content_type="text"),
        detect_misinformation(content[:2000], context_description="web page"),
        return_exceptions=True,
    )

    if not isinstance(gathered[0], BaseException):
        guard_result = gathered[0]
    if not isinstance(gathered[1], BaseException):
        misinfo_result = gathered[1]

    return {
        "is_ai": guard_result.get("is_ai_generated"),
        "confidence": guard_result.get("confidence"),
        "label": guard_result.get("label", "unknown"),
        "misinfo_detected": misinfo_result.get("misinformation_detected", False),
        "misinfo_type": misinfo_result.get("misinformation_type", "none"),
    }


def _slugify(text: str, max_len: int = 40) -> str:
    """Turn text into a filename-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len]


async def crawl_and_flag(
    query: str,
    urls: list[str] | None = None,
    max_pages: int = MAX_PAGES,
) -> Path:
    """
    Crawl URLs (or search for them), run AI detection on each page,
    and save flagged content to a .md report.

    Uses research_agent components for search, fetch, and deduplication
    so behaviour stays consistent with the /research pipeline.

    Args:
        query: Search query or topic description.
        urls: Optional explicit URLs. If None, searches via SearXNG.
        max_pages: Maximum number of pages to process.

    Returns:
        Path to the generated .md report file.
    """
    from research_agent.agent import _searxng_search
    from research_agent.fetcher import fetch_all
    from research_agent.deduplicator import deduplicate

    CRAWL_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = _slugify(query)
    report_path = CRAWL_DIR / f"{timestamp}_{slug}.md"

    # ── Step 1: Discover URLs ─────────────────────────────────────────────
    if not urls:
        urls = await _searxng_search(query, num_results=max_pages)

    if not urls:
        report_path.write_text(
            f"# Crawl Report: {query}\n\n_No URLs found._\n",
            encoding="utf-8",
        )
        return report_path

    urls = urls[:max_pages]

    # ── Step 2: Fetch & extract (research_agent.fetcher) ──────────────────
    pages = await fetch_all(urls)

    if not pages:
        report_path.write_text(
            f"# Crawl Report: {query}\n\n"
            f"_Fetched {len(urls)} URLs but none had extractable content._\n",
            encoding="utf-8",
        )
        return report_path

    # ── Step 3: Deduplicate (research_agent.deduplicator) ─────────────────
    unique_pages = await asyncio.to_thread(deduplicate, pages)
    logger.info("Dedup: %d → %d pages", len(pages), len(unique_pages))

    # ── Step 4: Run AI detection on each page ─────────────────────────────
    detection_tasks = [_detect_ai(p.text) for p in unique_pages]
    detections = await asyncio.gather(*detection_tasks, return_exceptions=True)

    # ── Step 5: Build markdown report ─────────────────────────────────────
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# Crawl Report: {query}",
        f"_Generated: {now}_",
        f"_Pages crawled: {len(unique_pages)} unique / {len(urls)} URLs_",
        "",
    ]

    flagged_count = 0
    for page, det in zip(unique_pages, detections):
        if isinstance(det, BaseException):
            det = {
                "is_ai": None, "confidence": None, "label": "error",
                "misinfo_detected": False, "misinfo_type": "none",
            }

        is_flagged = det["is_ai"] is True or det["misinfo_detected"]
        if is_flagged:
            flagged_count += 1

        conf = f"{det['confidence']:.0%}" if det["confidence"] is not None else "N/A"
        verdict = (
            "AI-generated" if det["is_ai"]
            else ("Human" if det["is_ai"] is False else "Inconclusive")
        )
        flag_marker = " **[FLAGGED]**" if is_flagged else ""

        lines.append("---")
        lines.append(f"## {page.domain}{flag_marker}")
        lines.append(f"**URL:** {page.url}")
        lines.append(
            f"**Verdict:** {verdict} | **Confidence:** {conf} | **Label:** {det['label']}"
        )
        if det["misinfo_detected"]:
            lines.append(f"**Misinformation:** {det['misinfo_type']}")
        lines.append("")
        preview = page.text[:500].replace("\n", " ")
        lines.append(f"> {preview}...")
        lines.append("")

    summary = (
        f"**Summary:** {flagged_count} of {len(unique_pages)} pages "
        f"flagged as AI-generated or misinformation.\n"
    )
    lines.insert(4, summary)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Crawl report saved to %s", report_path)
    return report_path

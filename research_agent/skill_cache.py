"""Skill cache: check local skill cards before re-searching the web."""

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("research/skills")


@dataclass
class SkillEntry:
    path: str
    topic: str
    last_updated: str
    confidence: str
    sources: list[str]
    content: str


def _parse_frontmatter(text: str) -> dict:
    """Extract YAML-like frontmatter from a skill card."""
    match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).splitlines():
        if ':' in line:
            key, val = line.split(':', 1)
            fm[key.strip()] = val.strip()
    return fm


def load_all_skills() -> list[SkillEntry]:
    """Load all skill cards from research/skills/."""
    skills = []
    if not SKILLS_DIR.exists():
        return skills

    for md_file in SKILLS_DIR.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(content)
            sources_raw = fm.get("sources", "[]")
            sources = re.findall(r'https?://[^\s,\]]+', sources_raw)
            skills.append(SkillEntry(
                path=str(md_file),
                topic=fm.get("topic", md_file.stem),
                last_updated=fm.get("last_updated", ""),
                confidence=fm.get("confidence", "low"),
                sources=sources,
                content=content,
            ))
        except Exception:
            logger.debug("Failed to load skill: %s", md_file)

    return skills


def lookup(query: str, skills: list[SkillEntry] | None = None) -> tuple[SkillEntry | None, float]:
    """
    Find the best-matching cached skill for a query.

    Returns:
        (skill, similarity) — skill is None if no match found, similarity is 0.0-1.0.
    """
    if skills is None:
        skills = load_all_skills()

    if not skills:
        return None, 0.0

    try:
        from research_agent.deduplicator import embed_texts, cosine_similarity

        query_emb = embed_texts([query])[0]
        topic_embs = embed_texts([s.topic for s in skills])

        best_idx = -1
        best_sim = 0.0
        for i, t_emb in enumerate(topic_embs):
            sim = cosine_similarity(query_emb, t_emb)
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        if best_idx >= 0:
            return skills[best_idx], best_sim
    except Exception:
        logger.exception("Skill cache embedding lookup failed")

    return None, 0.0

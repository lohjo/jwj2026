"""
research_agent/skill_cache.py — Similarity-based cache lookup.

Checks local research/skills/*.md cards before hitting the web again.
Threshold: 0.80 similarity → cache hit. Does NOT use sentence-transformers;
uses simple text-overlap heuristic to avoid heavy dependencies.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from config import RESEARCH_DIR

logger = logging.getLogger(__name__)

SKILLS_DIR = RESEARCH_DIR / "skills"


@dataclass
class SkillEntry:
    path: str
    topic: str
    last_updated: str
    confidence: str
    sources: list[str]
    content: str


def _parse_frontmatter(text: str) -> dict:
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}
    fm: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            fm[key.strip()] = val.strip()
    return fm


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load_all_skills() -> list[SkillEntry]:
    skills: list[SkillEntry] = []
    if not SKILLS_DIR.exists():
        return skills
    for md_file in SKILLS_DIR.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(content)
            sources_raw = fm.get("sources", "[]")
            sources = re.findall(r"https?://[^\s,\]]+", sources_raw)
            skills.append(
                SkillEntry(
                    path=str(md_file),
                    topic=fm.get("topic", md_file.stem),
                    last_updated=fm.get("last_updated", ""),
                    confidence=fm.get("confidence", "low"),
                    sources=sources,
                    content=content,
                )
            )
        except Exception:
            logger.debug("Failed to load skill: %s", md_file)
    return skills


def lookup(query: str, skills: list[SkillEntry] | None = None) -> tuple[SkillEntry | None, float]:
    """
    Find the best-matching cached skill for a query using Jaccard word overlap.

    Returns (skill, similarity). skill is None if no match found.
    """
    if skills is None:
        skills = load_all_skills()
    if not skills:
        return None, 0.0

    query_words = _word_set(query)
    best_idx = -1
    best_sim = 0.0

    for i, skill in enumerate(skills):
        topic_words = _word_set(skill.topic)
        sim = _jaccard(query_words, topic_words)
        if sim > best_sim:
            best_sim = sim
            best_idx = i

    if best_idx >= 0:
        return skills[best_idx], best_sim
    return None, 0.0

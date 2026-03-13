"""
SentinelRunner — wraps the Claude Code SDK with the full consistency stack:
  - CLAUDE.md: project-specific context loaded automatically by claude code
  - append_system_prompt: SENTINEL-specific behavioural rules on top
  - temperature=0: maximum determinism

Every file in this project calls sentinel_runner.run() instead of query()
directly, so the full stack is always applied.
"""

import asyncio
import logging
from pathlib import Path
from typing import AsyncGenerator

from claude_code_sdk import query, ClaudeCodeOptions, AssistantMessage

from config import SENTINEL_APPEND_PROMPT

logger = logging.getLogger(__name__)

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


class SentinelRunner:
    """
    Singleton runner. Import and call `sentinel_runner.run()` everywhere.
    Do not instantiate query() directly anywhere in the codebase.
    """

    def _build_options(self, extra_options: dict | None = None) -> ClaudeCodeOptions:
        """Build ClaudeCodeOptions with full consistency stack."""
        base = {
            "model": "claude-opus-4-6-20260101",
            "append_system_prompt": SENTINEL_APPEND_PROMPT,
            "cwd": _PROJECT_ROOT,
            "max_turns": 10,
        }
        if extra_options:
            base.update(extra_options)
        return ClaudeCodeOptions(**base)

    async def run(
        self,
        prompt: str,
        extra_options: dict | None = None,
    ) -> list:
        """
        Run a single prompt through the SDK and collect all messages.

        Args:
            prompt: The user or system prompt to send.
            extra_options: Override any option for this call only.

        Returns:
            List of all SDK message objects.
        """
        options = self._build_options(extra_options)
        messages = []

        try:
            async for msg in query(prompt=prompt, options=options):
                messages.append(msg)
                logger.debug("[SDK] message type: %s", type(msg).__name__)
        except Exception as e:
            logger.error("[SDK] Agent run failed: %s", e)

        return messages

    async def run_streaming(
        self,
        prompt: str,
        extra_options: dict | None = None,
    ) -> AsyncGenerator:
        """
        Streaming variant — yields messages as they arrive.
        Use this for long-running research or triage tasks.
        """
        options = self._build_options(extra_options)
        try:
            async for msg in query(prompt=prompt, options=options):
                yield msg
        except Exception as e:
            logger.error("[SDK] Streaming run failed: %s", e)


# Singleton — import this everywhere
sentinel_runner = SentinelRunner()

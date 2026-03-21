"""Google ADK root agent for SENTINEL."""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from config import GEMINI_MODEL, SENTINEL_APPEND_PROMPT
from pipeline.adk_callbacks import (
    after_model_callback,
    after_tool_callback,
    before_agent_callback,
)
from pipeline.adk_tools import (
    get_session_stats,
    run_guard_check,
    run_misinfo_check,
    run_research,
    run_text_detection,
)

logger = logging.getLogger(__name__)

SENTINEL_INSTRUCTION = f"""
You are SENTINEL, an AI content detection assistant for Singapore users.

## Core Capabilities
1. Use run_text_detection for full pipeline checks
2. Use run_guard_check for fast safety classification
3. Use run_misinfo_check for targeted misinformation analysis
4. Use run_research for web-supported checks
5. Use get_session_stats to report session activity

## Behavioural Rules
- Always respond in the same language as the user
- Keep responses concise and practical
- If evidence is weak, state uncertainty clearly
- Keep technical terms in English: AI-generated, deepfake, GUARD, OCR, confidence score

{SENTINEL_APPEND_PROMPT}
"""

root_agent = sentinel_agent = Agent(
    name="sentinel_agent",
    model=GEMINI_MODEL,
    instruction=SENTINEL_INSTRUCTION,
    description="SENTINEL AI content detection assistant for Singapore",
    tools=[
        run_text_detection,
        run_guard_check,
        run_misinfo_check,
        run_research,
        get_session_stats,
    ],
    before_agent_callback=before_agent_callback,
    after_model_callback=after_model_callback,
    after_tool_callback=after_tool_callback,
)


class SentinelADKRunner:
    """Singleton runner wrapping Google ADK for programmatic use."""

    def __init__(self) -> None:
        self._session_service = InMemorySessionService()
        self._runner = Runner(
            agent=sentinel_agent,
            app_name="sentinel",
            session_service=self._session_service,
        )

    async def run(
        self,
        prompt: str,
        session_id: str = "default",
    ) -> list:
        """Run a single prompt and collect all events."""
        events: list = []
        try:
            async for event in self._runner.run_async(
                session_id=session_id,
                user_id="sentinel_user",
                new_message=types.Content(
                    parts=[types.Part(text=prompt)], role="user"
                ),
            ):
                events.append(event)
                logger.debug("[ADK] event type: %s", type(event).__name__)
        except Exception as e:
            logger.error("[ADK] run failed: %s", e)
        return events

    async def run_streaming(
        self,
        prompt: str,
        session_id: str = "default",
    ) -> AsyncGenerator[object, None]:
        """Streaming variant — yields events as they arrive."""
        try:
            async for event in self._runner.run_async(
                session_id=session_id,
                user_id="sentinel_user",
                new_message=types.Content(
                    parts=[types.Part(text=prompt)], role="user"
                ),
            ):
                yield event
        except Exception as e:
            logger.error("[ADK] streaming run failed: %s", e)


adk_runner = SentinelADKRunner()
sentinel_runner = adk_runner


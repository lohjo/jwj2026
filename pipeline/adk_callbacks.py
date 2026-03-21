"""ADK lifecycle callbacks for SENTINEL detection pipeline telemetry."""

from __future__ import annotations

import logging
import time

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


async def before_agent_callback(callback_context: CallbackContext) -> None:
    """Initialize session state for SENTINEL detection tracking."""
    if "detection_count" not in callback_context.state:
        callback_context.state["detection_count"] = 0
        callback_context.state["session_start"] = time.time()
        callback_context.state["content_types_seen"] = []
    callback_context.state["temp:turn_start"] = time.time()


async def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    """Track detection calls for telemetry; pass response through unchanged."""
    callback_context.state["detection_count"] = (
        callback_context.state.get("detection_count", 0) + 1
    )
    return None


async def after_tool_callback(
    tool: object,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> dict | None:
    """Track which detection tools were invoked per session."""
    tool_name = getattr(tool, "name", str(tool))
    history: list = tool_context.state.get("content_types_seen", [])
    history.append({"tool": tool_name, "timestamp": time.time()})
    tool_context.state["content_types_seen"] = history[-50:]
    return None


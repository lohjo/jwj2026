"""ADK callbacks for semantic telemetry.

These hooks fire on agent lifecycle events and stream semantic data
to the WebSocket hub for frontend visualization.
"""

from __future__ import annotations

import logging
import time

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


async def before_agent_callback(callback_context: CallbackContext) -> None:
    """Initialize session state for semantic tracking."""
    if "event_count" not in callback_context.state:
        callback_context.state["event_count"] = 0
        callback_context.state["session_start"] = time.time()
        callback_context.state["modality_history"] = []
    callback_context.state["temp:turn_start"] = time.time()


async def after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> LlmResponse | None:
    """After the model responds, stream the agent's output into the semantic pipeline."""
    callback_context.state["event_count"] = callback_context.state.get("event_count", 0) + 1

    # Agent responses are meta-commentary, not semantic memories.
    # The agent can create memories explicitly via its ingest_text tool.
    return None  # pass through unchanged


async def after_tool_callback(
    tool: object,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> dict | None:
    """Track tool usage for trajectory analysis."""
    tool_name = getattr(tool, "name", str(tool))
    modality_history: list = tool_context.state.get("modality_history", [])
    modality_history.append({"tool": tool_name, "timestamp": time.time()})
    tool_context.state["modality_history"] = modality_history[-100:]
    return None  # pass through unchanged

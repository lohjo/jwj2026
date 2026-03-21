"""ADK tool definitions for SENTINEL detection capabilities."""

from __future__ import annotations

import time

from google.adk.tools import ToolContext


async def run_text_detection(text: str, tool_context: ToolContext) -> dict:
    """Run full detection pipeline on text content."""
    try:
        from pipeline.detector import run_full_detection

        result = await run_full_detection(text, content_type="text", source_lang="en")
        tool_context.state["last_detection"] = result
        return result
    except Exception:
        return {
            "detection_result": {"is_safe": None, "label": "api_error", "raw_response": {}, "safety_flag": None},
            "misinfo_result": {
                "misinformation_detected": False,
                "misinformation_type": "none",
                "claims": [],
                "explanation": "Unavailable.",
            },
            "manipulation_result": None,
            "insights_result": {"explanation": "Analysis unavailable.", "is_harmful": False, "llm_used": "failed"},
            "is_safe": None,
            "misinfo_type": "none",
        }


async def run_guard_check(text: str, tool_context: ToolContext) -> dict:
    """Run SEA-LION GUARD safety classification only."""
    try:
        from pipeline.guard import run_guard_detection

        return await run_guard_detection(text)
    except Exception:
        return {
            "is_safe": None,
            "label": "api_error",
            "raw_response": {},
            "safety_flag": None,
        }


async def run_misinfo_check(text: str, context: str, tool_context: ToolContext) -> dict:
    """Run misinformation detection on text content."""
    try:
        from pipeline.detector import detect_misinformation

        return await detect_misinformation(text, context_description=context)
    except Exception:
        return {
            "misinformation_detected": False,
            "misinformation_type": "none",
            "claims": [],
            "explanation": "Unavailable.",
        }


async def run_research(query: str, tool_context: ToolContext) -> dict:
    """Run web research and return summarised findings."""
    try:
        from research_agent.agent import research

        result = await research(query)
        tool_context.state["last_research"] = result
        return result
    except Exception as exc:
        return {"error": str(exc), "sources": [], "llm_used": "failed"}


async def get_session_stats(tool_context: ToolContext) -> dict:
    """Get current session detection statistics."""
    start = tool_context.state.get("session_start", time.time())
    return {
        "status": "success",
        "detection_count": tool_context.state.get("detection_count", 0),
        "session_duration_s": round(time.time() - start, 1),
        "tools_used": tool_context.state.get("content_types_seen", [])[-10:],
    }


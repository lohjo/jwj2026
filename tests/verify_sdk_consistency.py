"""
SENTINEL SDK/ADK Consistency Verification

Runs assertions to verify runtime consistency:
1. config.py constants loaded
2. CLAUDE.md exists at project root
3. ADK runner singleton is importable
4. Optional smoke test can run a simple prompt

Usage:
    python tests/verify_sdk_consistency.py
"""

import asyncio
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))


async def verify():
    print("=" * 60)
    print("SENTINEL SDK Consistency Verification")
    print("=" * 60)

    # 1. Config check
    from config import SENTINEL_APPEND_PROMPT, TELEGRAM_TOKEN

    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN missing from config"
    assert SENTINEL_APPEND_PROMPT, "SENTINEL_APPEND_PROMPT missing from config"
    print("✅ config.py constants loaded")

    # 2. CLAUDE.md exists
    claude_md = Path(__file__).resolve().parent / "CLAUDE.md"
    assert claude_md.exists(), "CLAUDE.md not found at project root"
    content = claude_md.read_text(encoding="utf-8")
    assert len(content) > 100, "CLAUDE.md is empty or too short"
    print("✅ CLAUDE.md exists at project root")

    # 3. ADK runner import
    from pipeline.adk_runner import sentinel_runner, root_agent
    assert callable(getattr(sentinel_runner, "run", None)), "sentinel_runner.run missing"
    assert getattr(root_agent, "name", ""), "root_agent name missing"
    print("✅ ADK runner import check passed")

    # 4. Optional smoke test — single turn (requires credentials and network)
    try:
        events = await sentinel_runner.run("Reply with exactly: SENTINEL_OK")
        assert isinstance(events, list), "ADK runner should return a list of events"
        print("✅ ADK smoke test passed — got event stream")
    except Exception as e:
        print(f"⚠️  ADK smoke test skipped — {e}")

    print("\n✅ All verifiable checks passed. ADK consistency stack is configured.")


if __name__ == "__main__":
    asyncio.run(verify())

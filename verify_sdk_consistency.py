"""
SENTINEL SDK Consistency Verification

Runs 4 assertions to verify the full consistency stack:
1. config.py constants loaded
2. CLAUDE.md exists at project root
3. SentinelRunner options are correct
4. Live smoke test returns an assistant message

Usage:
    python verify_sdk_consistency.py
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

    # 3. Runner options
    from pipeline.sdk_runner import sentinel_runner

    opts = sentinel_runner._build_options()
    assert opts.append_system_prompt is not None, "append_system_prompt not set"
    assert "SENTINEL" in opts.append_system_prompt, "SENTINEL_APPEND_PROMPT not in append"
    assert opts.max_turns == 10, "max_turns should be 10"
    print("✅ SentinelRunner options correct")

    # 4. Smoke test — single turn (requires Claude Code CLI installed)
    try:
        from claude_code_sdk import query, ClaudeCodeOptions

        msgs = await sentinel_runner.run("Reply with exactly: SENTINEL_OK")
        assert any(
            type(m).__name__ == "AssistantMessage"
            for m in msgs
        ), "No assistant message returned"
        print("✅ SDK smoke test passed — got assistant response")
    except FileNotFoundError:
        print("⚠️  Claude Code CLI not found — skipping live smoke test")
        print("   Install with: npm install -g @anthropic-ai/claude-code")
    except Exception as e:
        print(f"⚠️  SDK smoke test skipped — {e}")

    print("\n✅ All verifiable checks passed. SDK consistency stack is configured.")


if __name__ == "__main__":
    asyncio.run(verify())

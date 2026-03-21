"""
verify_live_api.py — Runtime smoke check for Gemini Live API (non-test path).

Runs a real call through media.live.live_voice_exchange using a local audio file.
This validates the actual Live API runtime integration, not mocked pytest coverage.

Usage:
    python verify_live_api.py
    python verify_live_api.py --audio tests/fixtures/test_audio.ogg
    python verify_live_api.py --context "GUARD verdict: AI-generated (0.85)"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

async def _run(audio_path: Path, context: str) -> int:
    try:
        from media.live import live_voice_exchange
    except SystemExit as e:
        print(f"[verify_live_api] ❌ Configuration error (missing required env var): {e}")
        return 2
    except ModuleNotFoundError as e:
        missing = e.name or str(e)
        print(f"[verify_live_api] ❌ Missing dependency: {missing}. Install project requirements first.")
        return 2

    audio_bytes = audio_path.read_bytes()
    reply_ogg = await live_voice_exchange(
        audio_bytes=audio_bytes,
        mime_type="audio/ogg",
        system_context=context,
    )

    print(f"[verify_live_api] input={audio_path} bytes={len(audio_bytes)}")
    print(f"[verify_live_api] output_ogg_bytes={len(reply_ogg)}")
    if reply_ogg:
        print("[verify_live_api] ✅ Live API returned audio bytes")
        return 0

    print("[verify_live_api] ❌ Live API returned empty bytes (fallback path)")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real Gemini Live API smoke call.")
    parser.add_argument(
        "--audio",
        default="tests/fixtures/test_audio.ogg",
        help="Input audio path (default: tests/fixtures/test_audio.ogg)",
    )
    parser.add_argument(
        "--context",
        default="GUARD verdict: AI-generated (0.85 confidence)",
        help="Detection context injected into Live API system instruction",
    )
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    if not audio_path.exists():
        print(f"[verify_live_api] ❌ Audio file not found: {audio_path}")
        return 2

    logging.basicConfig(level=logging.INFO)
    return asyncio.run(_run(audio_path, args.context))


if __name__ == "__main__":
    sys.exit(main())

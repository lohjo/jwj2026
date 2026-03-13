# PROMPT FOR CLAUDE OPUS 4.6
# SENTINEL — SDK Consistency Setup (Match Claude Code CLI Behaviour)

---

## CONTEXT

The Claude Agent SDK uses a **minimal system prompt by default**, which omits Claude
Code's coding guidelines, response style, tool instructions, and project context.
This causes SDK outputs to diverge significantly from what Claude Code CLI produces.

Your job is to implement the full consistency stack for the SENTINEL project so that
every SDK call behaves as close to `claude code` CLI as the API allows.

---

## STEP 0 — READ THESE FILES FIRST

Before writing any code, read all of the following. Do not skip any.

```
config.py
pipeline/insights.py        (or tools.py if pipeline/ doesn't exist yet)
telegram_bot.py
ai-agent-adk/agent.py
requirements.txt
CLAUDE.md                   (if it exists)
.env                        (variable names only — never log values)
```

After reading, confirm:
- Which files currently call `os.getenv()` directly (they should not — only `config.py` should)
- Whether a `CLAUDE.md` exists at project root
- Whether `anthropic-agent-sdk` is in `requirements.txt`

---

## STEP 1 — INSTALL THE AGENT SDK

Add to `requirements.txt` if not already present:

```
anthropic-agent-sdk>=0.4
```

Verify it is importable:

```python
from anthropic_agent_sdk import query
print("Agent SDK OK")
```

---

## STEP 2 — CREATE CLAUDE.md AT PROJECT ROOT

Create `CLAUDE.md` at the project root (same level as `telegram_bot.py`).
This file is automatically read by the Agent SDK when `setting_sources` includes
`"project"`. It is the persistent memory that survives across all sessions.

```markdown
# SENTINEL — AI-Generated Content Detection Bot

## Architecture Overview
- Frontend: Telegram Bot API (python-telegram-bot)
- Backend: Google ADK multi-agent orchestration
- Detection: SEA-LION GUARD → Gemini 1.5-flash (→ Groq llama-3.3-70b fallback)
- Translation: SEA-LION Gemma 9B-IT (all languages)
- STT: Deepgram Nova-2 | TTS: ElevenLabs eleven_multilingual_v2
- Logging: ClickHouse Cloud (clickhouse-connect, async_insert=1)
- Research: Firecrawl API → research/summaries/ + research/skills/

## Critical Code Rules
- `parse_mode="HTML"` everywhere — NEVER MarkdownV2
- `clickhouse-connect` only — NEVER `clickhouse-driver`
- All external API calls wrapped in try/except — nothing propagates to Telegram handler
- All structured returns are dicts — never raise from detection functions
- Temp files (audio, images, TTS) ALWAYS deleted in `finally` blocks
- `len(text) >= 20` guard before calling langdetect
- `asyncio.to_thread()` for ALL sync blocking calls inside async handlers

## Dependency Rule
- `config.py` is the ONLY file that calls `os.getenv()`
- All other files import constants from `config.py`

## Translation Flow (non-negotiable order)
1. User input arrives
2. `detect_language(text)` → ISO 639-1 code
3. If lang != "en": `translate_to_english(text, lang)` via SEA-LION Gemma 9B
4. `run_guard_detection(english_text)`
5. `detect_misinformation(english_text)`
6. `detect_image_manipulation(file_path)` (images/video only)
7. `call_llm(insights_prompt)` → English explanation
8. If lang != "en": `translate_from_english(explanation, lang)` via SEA-LION Gemma 9B
9. `format_detection_message()` → HTML reply
10. Send reply + optional TTS voice note

## Translation Rules
- Pre-detection (non-EN → EN): preserve EXACT phrasing — do NOT fix grammar
- Post-detection (EN → user lang): translate naturally and fluently
- Always keep these terms in English: AI-generated, deepfake, GUARD, OCR, confidence score
- Singlish input → translate to standard Singapore English
- Audio: use Deepgram's `detected_language`, NOT langdetect

## LLM Call Pattern
- All LLM calls go through `pipeline/insights.py::call_llm()` ONLY
- Primary: Gemini 1.5-flash
- Fallback: Groq llama-3.3-70b-versatile (triggers on ANY Gemini exception)
- Groq uses `openai` package with `base_url=GROQ_API_BASE` — no separate groq package
- Log `model_versions["llm_used"] = "gemini" | "groq" | "failed"` to ClickHouse

## Model Registry
| Role            | Model ID                                  |
|-----------------|-------------------------------------------|
| Guard           | aisingapore/SEA-LION-GUARD                |
| Translation     | aisingapore/SEA-LION-v4-Gemma-9B-IT       |
| Primary LLM     | gemini-1.5-flash                          |
| Fallback LLM    | groq/llama-3.3-70b-versatile              |
| STT             | deepgram nova-2-general                   |
| TTS             | elevenlabs eleven_multilingual_v2          |

## File Structure (canonical)
```
sentinel/
├── config.py               ← only file that reads .env
├── telegram_bot.py         ← handlers only, no business logic
├── pipeline/
│   ├── detector.py         ← orchestrates all three detections
│   ├── guard.py            ← SEA-LION GUARD only
│   ├── insights.py         ← call_llm() with Gemini→Groq fallback
│   ├── translator.py       ← detect_language, translate_to/from_english
│   ├── formatter.py        ← format_detection_message() HTML only
│   └── logger.py           ← log_to_clickhouse() non-blocking
├── media/
│   ├── image.py            ← OCR + manipulation detection
│   ├── audio.py            ← Deepgram STT + ElevenLabs TTS
│   └── video.py            ← OpenCV + ffmpeg
├── research_agent/
│   ├── agent.py            ← research() entrypoint
│   ├── crawler.py          ← Firecrawl API
│   ├── summariser.py       ← LLM → .md output
│   └── skill_cache.py      ← similarity-based cache
└── tests/
    ├── test_guard.py
    ├── test_insights.py
    ├── test_translator.py
    ├── test_formatter.py
    ├── test_audio.py
    ├── test_logger.py
    └── test_research_agent.py
```

## Testing Rules
- Every non-trivial function has a pytest test
- Mock ALL external API calls — never hit real APIs in tests
- Use `pytest-asyncio` for all async functions
- `log_to_clickhouse()` must never raise in any test scenario
```

---

## STEP 3 — ADD SENTINEL_APPEND_PROMPT TO config.py

Add this constant to the bottom of `config.py`. It is injected into every SDK call
via `append` and captures all SENTINEL-specific behavioural rules that are NOT
already in CLAUDE.md (which is for project context) or the `claude_code` preset
(which handles tool usage and general coding style).

```python
# config.py — append this block at the bottom

SENTINEL_APPEND_PROMPT = """
## SENTINEL Behavioural Rules (Agent SDK Session)

### Output Format
- Always reply in the same language as the user's input — this is non-negotiable
- Use parse_mode HTML only — never MarkdownV2
- Verdict labels: ✅ Human-Written | 🤖 AI-Generated | ❓ Unclear | 🚨 AI + Harmful
- Harmful flag (🚨) only when is_ai_generated=True AND is_harmful=True simultaneously

### Code Generation Standards
- Return type: always a dict — never raise from detection or translation functions
- Async: all external I/O must be awaited or wrapped in asyncio.to_thread()
- Error handling: try/except around every external call, log to stderr, return fallback
- No blocking calls inside Telegram event loop handlers
- Use TypedDict or dataclass for all function signatures when adding new functions

### LLM Fallback Pattern
When generating code that calls an LLM:
1. Try Gemini first via pipeline/insights.py::call_llm()
2. On ANY exception (not just rate limits): fall back to Groq automatically
3. Set model_versions["llm_used"] = "gemini" | "groq" | "failed" in every ClickHouse row
4. Return "" on total failure — callers must handle empty string explicitly

### Detection Return Shape
Every detection function must return exactly this shape on failure — no exceptions:
```python
# run_guard_detection() fallback
{"is_ai_generated": None, "confidence": None, "label": "api_error", "raw_response": {}}

# detect_misinformation() fallback
{"misinformation_detected": False, "misinformation_type": "unknown",
 "claims": [], "explanation": "Unavailable.", "confidence": 0.0}

# detect_image_manipulation() fallback
{"manipulation_detected": False, "manipulation_type": "unknown",
 "signals": [], "explanation": "Unavailable.", "confidence": 0.0}
```

### ClickHouse Insert Rules
- Always use: settings={"async_insert": 1, "wait_for_async_insert": 0}
- Always call via: asyncio.to_thread(log_to_clickhouse, row_dict)
- log_to_clickhouse() must NEVER raise — swallow all exceptions, log to stderr

### Research Agent Rules
- Always check skill_cache before searching (similarity threshold: 0.80)
- Write to research/summaries/{YYYYMMDD}_{slug}.md after every run
- Write to research/skills/{slug}.md after every run
- Use Firecrawl /search endpoint — do NOT use raw httpx for page fetching
- onlyMainContent: true in all Firecrawl requests
"""
```

---

## STEP 4 — CREATE THE SDK RUNNER (pipeline/sdk_runner.py)

Create this file. It is the single entrypoint for all Claude Agent SDK calls in the
project. No other file should instantiate `query()` directly.

```python
# pipeline/sdk_runner.py

"""
SentinelRunner — wraps the Claude Agent SDK with the full consistency stack:
  - claude_code preset: loads Claude Code's full 110+ component system prompt
  - CLAUDE.md: project-specific context via setting_sources=["project"]
  - append: SENTINEL-specific behavioural rules on top
  - temperature=0: maximum determinism

This is as close to `claude code` CLI behaviour as the SDK allows.
"""

import asyncio
import logging
from typing import AsyncGenerator

from anthropic_agent_sdk import query

from config import SENTINEL_APPEND_PROMPT

logger = logging.getLogger(__name__)


class SentinelRunner:
    """
    Singleton runner. Import and call `sentinel_runner.run()` everywhere.
    Do not instantiate query() directly anywhere in the codebase.
    """

    BASE_OPTIONS: dict = {
        "model": "claude-opus-4-6-20260101",
        "system_prompt": {
            "type": "preset",
            "preset": "claude_code",          # full Claude Code system prompt
            "append": SENTINEL_APPEND_PROMPT  # SENTINEL-specific rules appended
        },
        "setting_sources": ["project"],       # loads CLAUDE.md from project root
        "temperature": 0,                     # maximum determinism
        "max_turns": 10,
    }

    async def run(
        self,
        prompt: str,
        extra_options: dict | None = None
    ) -> list:
        """
        Run a single prompt through the SDK and collect all messages.

        Args:
            prompt: The user or system prompt to send.
            extra_options: Override any BASE_OPTIONS key for this call only.

        Returns:
            List of all SDK message objects.
        """
        options = {**self.BASE_OPTIONS, **(extra_options or {})}
        messages = []

        try:
            async for msg in query(prompt=prompt, options=options):
                messages.append(msg)
                logger.debug(f"[SDK] message type: {msg.type}")
        except Exception as e:
            logger.error(f"[SDK] Agent run failed: {e}")

        return messages

    async def run_streaming(
        self,
        prompt: str,
        extra_options: dict | None = None
    ) -> AsyncGenerator:
        """
        Streaming variant — yields messages as they arrive.
        Use this for long-running research or triage tasks.
        """
        options = {**self.BASE_OPTIONS, **(extra_options or {})}
        try:
            async for msg in query(prompt=prompt, options=options):
                yield msg
        except Exception as e:
            logger.error(f"[SDK] Streaming run failed: {e}")


# Singleton — import this everywhere
sentinel_runner = SentinelRunner()
```

---

## STEP 5 — UPDATE ALL EXISTING RUNNER USAGE

Find every place in the codebase that either:
- Calls `Runner(...)` from `google.adk`
- Calls `genai.GenerativeModel(...).generate_content(...)` directly outside of `call_llm()`
- Calls `query()` from `anthropic_agent_sdk` directly

Replace them with:

```python
from pipeline.sdk_runner import sentinel_runner

# Instead of any direct SDK/ADK call:
messages = await sentinel_runner.run(prompt)

# Or streaming:
async for msg in sentinel_runner.run_streaming(prompt):
    process(msg)
```

---

## STEP 6 — VERIFY THE CONSISTENCY STACK

Run this verification script after implementation. All assertions must pass.

```python
# verify_sdk_consistency.py

import asyncio
from pipeline.sdk_runner import sentinel_runner
from config import SENTINEL_APPEND_PROMPT, TELEGRAM_TOKEN

async def verify():
    print("=" * 60)
    print("SENTINEL SDK Consistency Verification")
    print("=" * 60)

    # 1. Config check
    assert TELEGRAM_TOKEN, "TELEGRAM_TOKEN missing from config"
    assert SENTINEL_APPEND_PROMPT, "SENTINEL_APPEND_PROMPT missing from config"
    print("✅ config.py constants loaded")

    # 2. CLAUDE.md exists
    from pathlib import Path
    assert Path("CLAUDE.md").exists(), "CLAUDE.md not found at project root"
    print("✅ CLAUDE.md exists at project root")

    # 3. Runner options
    opts = sentinel_runner.BASE_OPTIONS
    assert opts["system_prompt"]["preset"] == "claude_code", "claude_code preset not set"
    assert "project" in opts["setting_sources"], "setting_sources missing 'project'"
    assert opts["temperature"] == 0, "temperature must be 0 for determinism"
    assert "append" in opts["system_prompt"], "SENTINEL_APPEND_PROMPT not appended"
    print("✅ SentinelRunner BASE_OPTIONS correct")

    # 4. Smoke test — single turn
    msgs = await sentinel_runner.run("Reply with exactly: SENTINEL_OK")
    assert any(
        hasattr(m, "type") and m.type == "assistant"
        for m in msgs
    ), "No assistant message returned"
    print("✅ SDK smoke test passed — got assistant response")

    print("\n✅ All checks passed. SDK is consistent with Claude Code CLI.")

asyncio.run(verify())
```

---

## STEP 7 — SUMMARY OF CONSISTENCY MECHANISMS

| Mechanism | What it does | Where configured |
|---|---|---|
| `preset: "claude_code"` | Loads full 110+ component Claude Code system prompt | `SentinelRunner.BASE_OPTIONS` |
| `setting_sources: ["project"]` | Loads `CLAUDE.md` from project root | `SentinelRunner.BASE_OPTIONS` |
| `append: SENTINEL_APPEND_PROMPT` | Adds SENTINEL-specific rules on top of preset | `config.py` + `SentinelRunner` |
| `temperature: 0` | Maximum output determinism | `SentinelRunner.BASE_OPTIONS` |
| `CLAUDE.md` | Persistent project memory — architecture, rules, file structure | Project root |
| `sentinel_runner` singleton | Single entrypoint — no raw `query()` calls elsewhere | `pipeline/sdk_runner.py` |

---

## CONSTRAINTS

- Do not remove the `claude_code` preset — it is what closes the gap with CLI behaviour
- Do not set `temperature > 0` — determinism is required for consistent detection output
- `CLAUDE.md` and `SENTINEL_APPEND_PROMPT` are complementary — do not merge them into one
- `sentinel_runner` is a singleton — do not instantiate `SentinelRunner()` elsewhere
- The `append` field adds to the preset — it does NOT replace it
- Verify with `verify_sdk_consistency.py` before committing any changes to the runner
# PROMPT FOR CLAUDE OPUS 4.6
# SENTINEL — Full Project Triage, Simplification & Refactor

---

## YOUR ROLE

You are a senior Python architect performing a full triage of the SENTINEL codebase —
a multimodal AI-generated content detection Telegram bot. Your job is to:

1. Read every file in the project
2. Identify redundancy, dead code, over-engineering, and broken patterns
3. Produce a simplified, production-ready refactor with a clean dependency graph
4. Write unit tests for every non-trivial function

Do not preserve bad patterns out of caution. Simplify aggressively where it is safe to
do so. Explain every structural decision you make.

---

## STEP 0 — READ THE ENTIRE PROJECT FIRST

Before writing a single line of code, read ALL of the following files in full.
Do not skip any. Use the Read tool on each:

```
telegram_bot.py
tools.py
image_detector.py
video_detector.py
ocr.py
config.py
detect_cli.py
ai-agent-adk/agent.py
ai-agent-adk/tools.py
ai-agent-adk/translator.py
ai-agent-adk/chat-cli.py
research_agent/agent.py          (if exists)
research_agent/fetcher.py        (if exists)
research_agent/skill_cache.py    (if exists)
requirements.txt
.env                             (read variable names only — never log values)
```

After reading, produce a **triage report** in this format before touching any code:

```markdown
## TRIAGE REPORT

### Broken / Non-functional
- list each broken pattern with file + line reference

### Redundant / Duplicated
- list duplicated logic across files

### Over-engineered
- list things that are more complex than needed

### Missing
- list things that are needed but absent

### Dependency Graph (current)
- ascii diagram showing how files import each other

### Proposed Dependency Graph (simplified)
- ascii diagram of the refactored structure
```

Wait for user approval of the triage report before proceeding to refactor.

---

## STEP 1 — REFACTORED PROJECT STRUCTURE

After triage approval, produce this exact file structure.
Do not deviate without explaining why.

```
sentinel/
├── .env                        # unchanged
├── requirements.txt            # updated
├── config.py                   # single source of truth for all env vars
├── telegram_bot.py             # handlers only — no business logic
├── pipeline/
│   ├── __init__.py
│   ├── detector.py             # orchestrates guard + misinfo + manipulation
│   ├── guard.py                # SEA-LION GUARD calls only
│   ├── insights.py             # Gemini → Groq fallback LLM calls
│   ├── translator.py           # SEA-LION translation (input→EN, EN→output lang)
│   ├── formatter.py            # format_detection_message() — HTML only
│   └── logger.py               # log_to_clickhouse() — async, non-blocking
├── media/
│   ├── __init__.py
│   ├── image.py                # image download + OCR + manipulation detection
│   ├── audio.py                # Deepgram STT + ElevenLabs TTS
│   └── video.py                # OpenCV frame sampling + ffmpeg audio
├── research_agent/
│   ├── __init__.py
│   ├── agent.py                # research(query) entrypoint
│   ├── crawler.py              # Firecrawl API wrapper
│   ├── summariser.py           # LLM summarisation → .md output
│   └── skill_cache.py          # similarity-based cache lookup
├── research/
│   ├── raw/                    # {YYYYMMDD}_{slug}/ folders
│   ├── summaries/              # {YYYYMMDD}_{slug}.md
│   └── skills/                 # {topic}.md skill cards
└── tests/
    ├── __init__.py
    ├── test_guard.py
    ├── test_insights.py
    ├── test_translator.py
    ├── test_formatter.py
    ├── test_logger.py
    ├── test_image.py
    ├── test_audio.py
    ├── test_video.py
    └── test_research_agent.py
```

---

## STEP 2 — CONFIG (config.py)

Centralise ALL environment variables here. No other file should call `os.getenv()`
directly — they must import from `config.py`.

```python
# config.py
from pathlib import Path
from dotenv import load_dotenv
import os, sys

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        sys.exit(f"[SENTINEL] Missing required env var: {key}")
    return val

def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)

# ── Telegram ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN       = _require("TELEGRAM_TOKEN")

# ── SEA-LION ────────────────────────────────────────────────────────────
SEALION_API_BASE     = _optional("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
SEALION_API_KEY      = _require("OPENAI_API_KEY")
GUARD_MODEL          = _optional("GUARD_MODEL", "aisingapore/SEA-LION-GUARD")
SEALION_MODEL        = _optional("MODEL", "aisingapore/Llama-SEA-LION-v3-70B-IT")
TRANSLATOR_MODEL     = _optional("TRANSLATOR_MODEL", "aisingapore/SEA-LION-v4-Gemma-9B-IT")

# ── Primary LLM: Gemini ─────────────────────────────────────────────────
GEMINI_API_KEY       = _require("GEMINI_API_KEY")
GEMINI_MODEL         = _optional("GEMINI_MODEL", "gemini-1.5-flash")

# ── Fallback LLM: Groq ──────────────────────────────────────────────────
GROQ_API_KEY         = _require("GROQ_API_KEY")
GROQ_MODEL           = _optional("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_BASE        = "https://api.groq.com/openai/v1"

# ── Speech ──────────────────────────────────────────────────────────────
DEEPGRAM_API_KEY     = _require("DEEPGRAM_API_KEY")
ELEVENLABS_API_KEY   = _require("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID  = _require("ELEVENLABS_VOICE_ID")

# ── ClickHouse ──────────────────────────────────────────────────────────
CLICKHOUSE_HOST      = _require("CLICKHOUSE_HOST")
CLICKHOUSE_PORT      = int(_optional("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER      = _optional("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD  = _require("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DB        = _optional("CLICKHOUSE_DB", "agent_logs")

# ── Research Agent ──────────────────────────────────────────────────────
FIRECRAWL_API_KEY    = _require("FIRECRAWL_API_KEY")
RESEARCH_DIR         = Path(_optional("RESEARCH_DIR", "research"))

# ── Rate limiting ────────────────────────────────────────────────────────
COOLDOWN_SECONDS     = float(_optional("COOLDOWN_SECONDS", "3.0"))
```

---

## STEP 3 — LLM CALL PATTERN (Gemini → Groq fallback)

All LLM calls — in `pipeline/insights.py`, `research_agent/summariser.py`, and
anywhere else that calls a generative model — MUST use this exact fallback pattern.
Never call Gemini or Groq directly inline. Always go through `call_llm()`.

```python
# pipeline/insights.py  (or a shared llm.py utility)

import google.generativeai as genai
from openai import OpenAI
import logging
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    GROQ_API_KEY, GROQ_MODEL, GROQ_API_BASE
)

async def call_llm(prompt: str, max_tokens: int = 1024) -> str:
    """
    Call Gemini 1.5-flash. If it fails for ANY reason (rate limit, timeout,
    quota, API error), transparently fall back to Groq llama-3.3-70b.

    Never raises — returns empty string on total failure.

    Args:
        prompt: Full prompt string to send.
        max_tokens: Max output tokens.

    Returns:
        Response text string, or "" on failure.
    """
    # ── Primary: Gemini ─────────────────────────────────────────────────
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens)
        )
        text = response.text.strip()
        if text:
            logging.debug("[LLM] Gemini OK")
            return text
        raise ValueError("Empty Gemini response")

    except Exception as gemini_err:
        logging.warning(f"[LLM] Gemini failed ({gemini_err}), falling back to Groq")

    # ── Fallback: Groq ──────────────────────────────────────────────────
    try:
        client = OpenAI(api_key=GROQ_API_KEY, base_url=GROQ_API_BASE)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            timeout=20.0
        )
        text = response.choices[0].message.content.strip()
        logging.info("[LLM] Groq fallback OK")
        return text

    except Exception as groq_err:
        logging.error(f"[LLM] Both Gemini and Groq failed. Groq error: {groq_err}")
        return ""
```

**Rules:**
- Every caller checks if the return is `""` and handles it gracefully
- Log which model was used at `DEBUG` level so it appears in ClickHouse `model_versions`
- Add `"llm_used": "gemini" | "groq" | "failed"` to every ClickHouse log row

---

## STEP 4 — LANGUAGE I/O (SEA-LION Translation)

This is the most critical correctness requirement. The bot MUST reply in the same
language the user wrote in.

### Exact flow

```
User input (any language)
    │
    ▼
detect_language(text)           ← langdetect, min 20 chars, else default "en"
    │
    ├── if lang == "en" ────────── skip translate_to_english()
    │
    └── if lang != "en" ─────────► translate_to_english(text, lang)
                                        │ SEA-LION Gemma 9B-IT
                                        ▼
                                   [english_text]
                                        │
                                        ▼
                              run_guard_detection(english_text)
                              detect_misinformation(english_text)
                              detect_image_manipulation(file_path)  ← images only
                                        │
                                        ▼
                              call_llm(insights_prompt)  ← produces English explanation
                                        │
                                        ▼
                              if lang != "en":
                                translate_from_english(explanation, lang)
                                        │
                                        ▼
                              format_detection_message(translated_explanation)
                                        │
                                        ▼
                              reply_text (+ TTS voice note if input was audio)
```

### translator.py spec

```python
# pipeline/translator.py

SUPPORTED_LANGUAGES = {"zh", "ms", "ta", "id", "th", "vi", "tl"}
SINGLISH_LANGS = {"en-sg", "sg"}  # normalise to "en"

async def detect_language(text: str) -> str:
    """
    Returns ISO 639-1 code. Returns 'en' for short text (< 20 chars),
    Singlish, or on detection failure.
    """

async def translate_to_english(text: str, source_lang: str,
                                runner, user_id: str, session_id: str) -> str:
    """
    Translate non-English text to English before detection.
    CRITICAL: Preserve original phrasing — do NOT fix grammar or paraphrase.
    Return original text unchanged on failure (fail-safe).
    """

async def translate_from_english(text: str, target_lang: str,
                                  runner, user_id: str, session_id: str) -> str:
    """
    Translate English explanation back to user's language.
    Keep these terms in English regardless of target language:
        AI-generated, deepfake, GUARD, OCR, SEA-LION, confidence score
    Return English text unchanged on failure (fail-safe).
    """
```

### SEA-LION translator prompt (use verbatim)

```
You are a precise translator. Translate the following text from {source} to {target}.

Rules:
- If translating TO English (pre-detection): preserve ALL original phrasing, grammar
  errors, and vocabulary exactly. Do NOT improve or paraphrase. Literal translation only.
- If translating FROM English (post-detection): translate naturally and fluently.
  Keep these words in English: AI-generated, deepfake, GUARD, OCR, confidence score.
- For Singlish input: translate to standard Singapore English.
- Output the translation ONLY. No preamble, no explanation, no quotation marks.

Text to translate:
{text}
```

---

## STEP 5 — STT/TTS (Deepgram + ElevenLabs)

### media/audio.py spec

```python
async def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe audio file using Deepgram Nova-2.

    Returns:
        {
          "transcript": str,            # full transcript text
          "detected_language": str,     # ISO 639-1 from Deepgram (more reliable than langdetect for audio)
          "confidence": float,          # word-level avg confidence
          "duration_seconds": float
        }
    On failure: returns {"transcript": "", "detected_language": "en", "confidence": 0.0, "duration_seconds": 0.0}

    Implementation notes:
    - Use Deepgram Python SDK v3+ (not REST directly)
    - Enable detect_language=True in transcription options
    - Model: nova-2-general
    - Supported input formats: .ogg, .mp3, .wav, .m4a
    - Max file size: 25MB — reject and return error dict above if exceeded
    """

async def synthesise_speech(text: str, output_path: str,
                             language: str = "en") -> str:
    """
    Generate voice note using ElevenLabs eleven_multilingual_v2.

    Args:
        text: Text to synthesise (will be truncated to 500 chars if longer)
        output_path: Where to save the .mp3 file
        language: ISO 639-1 code — passed as language_code hint to ElevenLabs

    Returns:
        output_path on success, "" on failure (caller must handle empty string)

    Implementation notes:
    - Use ElevenLabs Python SDK (elevenlabs>=1.0)
    - Model: eleven_multilingual_v2
    - Voice: ELEVENLABS_VOICE_ID from config
    - Do NOT synthesise if text is under 10 chars
    - Always clean up temp files in finally block
    """
```

### Audio handler flow (telegram_bot.py)

```python
async def handle_audio(update, context):
    # 1. Download .ogg file to temp path
    # 2. transcribe_audio(temp_path) → {transcript, detected_language, confidence}
    # 3. Use detected_language (not langdetect) as source_lang
    # 4. translate_to_english(transcript, detected_language, ...)
    # 5. run_guard_detection + detect_misinformation
    # 6. call_llm(insights prompt)
    # 7. translate_from_english(explanation, detected_language, ...)
    # 8. format_detection_message(...)
    # 9. CONCURRENTLY:
    #       reply_text (text verdict)
    #       synthesise_speech(explanation, tts_path, detected_language) → voice note
    # 10. If voice note produced: send_voice(tts_path)
    # 11. log_to_clickhouse(...) — background task, never awaited in handler
    # 12. finally: delete temp audio + tts files
```

---

## STEP 6 — RESEARCH AGENT (Firecrawl)

Replace the existing httpx + trafilatura fetcher with the Firecrawl API.

### research_agent/crawler.py spec

```python
import httpx
from config import FIRECRAWL_API_KEY

FIRECRAWL_BASE = "https://api.firecrawl.dev/v1"

async def scrape_url(url: str) -> dict:
    """
    Scrape a single URL using Firecrawl /scrape endpoint.

    Returns:
        {
          "url": str,
          "title": str,
          "markdown": str,     # clean markdown — use this, not raw HTML
          "word_count": int,
          "success": bool
        }

    Implementation:
    - POST to {FIRECRAWL_BASE}/scrape
    - Headers: Authorization: Bearer {FIRECRAWL_API_KEY}
    - Body: {"url": url, "formats": ["markdown"], "onlyMainContent": true}
    - Timeout: 20s
    - Return success=False dict on any failure — never raise
    - Discard pages with word_count < 150
    """

async def search_and_scrape(query: str, num_results: int = 6) -> list[dict]:
    """
    Use Firecrawl /search endpoint to find + scrape top results in one call.

    Returns list of scrape_url() dicts, filtered to word_count >= 150.

    POST to {FIRECRAWL_BASE}/search
    Body: {"query": query, "limit": num_results, "scrapeOptions": {"formats": ["markdown"]}}
    """
```

### research_agent/summariser.py spec

```python
async def summarise(query: str, scraped_pages: list[dict]) -> dict:
    """
    Produce structured summary from scraped pages.

    Args:
        query: Original research query
        scraped_pages: List of dicts from crawler.search_and_scrape()

    Returns:
        {
          "summary_md": str,     # human-readable .md summary
          "skill_md": str,       # model-facing skill card (see format below)
          "sources": list[str],  # URLs used
          "llm_used": str        # "gemini" | "groq"
        }

    The LLM prompt MUST instruct the model to output a JSON object with keys:
        summary_md, skill_md
    Parse JSON before returning. Strip ```json fences before parsing.
    """

SUMMARY_PROMPT = """
You are a research analyst. Summarise the following web content into two documents.

Query: {query}

Sources:
{sources_text}

Respond ONLY with a JSON object (no markdown fences):
{{
  "summary_md": "# {query}\\n\\n## Overview\\n...\\n\\n## Key Findings\\n...\\n\\n## Sources\\n...",
  "skill_md": "---\\ntopic: {topic_slug}\\nlast_updated: {today}\\nsources: [...]\\nconfidence: high|medium|low\\n---\\n\\n# {query}\\n\\n## Key Facts\\n- ...\\n\\n## Code Patterns\\n```\\n# if applicable\\n```\\n\\n## Gotchas\\n- ...\\n\\n## Do Not Search Again If\\n- ..."
}}

Rules:
- summary_md is for humans: clear prose, headers, bullet points
- skill_md is for the AI model: facts only, no filler, include working code if relevant
- Both must directly answer the query using the sources provided
- Do not invent facts not present in the sources
"""
```

### research_agent/agent.py output contract

```python
async def research(query: str, force_refresh: bool = False) -> dict:
    """
    Main entrypoint.

    Returns:
        {
          "summary_path": str,    # research/summaries/YYYYMMDD_{slug}.md
          "skill_path": str,      # research/skills/{slug}.md
          "cache_hit": bool,
          "sources": list[str],
          "raw_dir": str,         # research/raw/YYYYMMDD_{slug}/
          "llm_used": str
        }

    Side effects:
        - Writes summary .md to research/summaries/
        - Writes skill card .md to research/skills/
        - Writes raw scraped text files to research/raw/{slug}/
        - All directories created automatically if they don't exist
    """
```

---

## STEP 7 — UNIT TESTS

Write pytest tests for every module. Use `pytest-asyncio` for async functions.
Mock all external API calls — never hit real APIs in tests.

### tests/test_guard.py
```python
# Test run_guard_detection():
# - returns correct dict shape on success
# - returns label="api_error" on HTTP 500 (not "detection_failed")
# - returns label="timeout" on asyncio.TimeoutError
# - returns label="api_key_missing" if SEALION_API_KEY is ""
# - correctly parses "AI-generated" verdict
# - correctly parses "Human-generated" verdict
# - correctly parses "Inconclusive" verdict
# - handles unrecognised response format gracefully
```

### tests/test_insights.py
```python
# Test call_llm():
# - returns Gemini response when Gemini succeeds
# - falls back to Groq when Gemini raises any Exception
# - returns "" when both Gemini and Groq fail
# - never raises
# - includes correct "llm_used" value in logs
```

### tests/test_translator.py
```python
# Test detect_language():
# - returns "en" for text under 20 chars
# - returns "zh" for Chinese text
# - returns "ms" for Malay text
# - returns "en" on langdetect exception
# - normalises "en-sg" Singlish to "en"

# Test translate_to_english():
# - returns original text unchanged on API failure (fail-safe)
# - called with source_lang="en" returns text unchanged (no API call)

# Test translate_from_english():
# - returns English unchanged on API failure (fail-safe)
# - called with target_lang="en" returns text unchanged (no API call)
```

### tests/test_formatter.py
```python
# Test format_detection_message():
# - outputs valid HTML (no MarkdownV2 syntax)
# - verdict "✅ Human-Written" when is_ai=False
# - verdict "🤖 AI-Generated" when is_ai=True and not harmful
# - verdict "🚨 AI + Harmful" when is_ai=True and is_harmful=True
# - verdict "❓ Unclear" when is_ai=None
# - context note appears only when confidence 30–70%
# - never contains MarkdownV2 special chars: ( ) - . ! #
```

### tests/test_audio.py
```python
# Test transcribe_audio():
# - returns correct dict shape on success (mock Deepgram SDK)
# - returns empty transcript dict on SDK exception
# - rejects files over 25MB
# - uses detected_language from Deepgram, not langdetect

# Test synthesise_speech():
# - returns output_path on success (mock ElevenLabs SDK)
# - returns "" on SDK exception
# - does not call API for text under 10 chars
# - truncates text at 500 chars before API call
```

### tests/test_logger.py
```python
# Test log_to_clickhouse():
# - never raises on ClickHouse exception
# - correctly passes async_insert=1, wait_for_async_insert=0
# - logs "llm_used" field in model_versions Map
# - silently swallows all errors to stderr
```

### tests/test_research_agent.py
```python
# Test scrape_url():
# - returns success=False dict on HTTP error (never raises)
# - filters pages with word_count < 150
# - uses onlyMainContent=true in Firecrawl request

# Test research():
# - uses skill cache when similarity > 0.80 (mock cache)
# - writes summary .md to correct path
# - writes skill card .md to correct path
# - creates raw/ directory and saves per-source files
# - sets cache_hit=True when cache used
```

---

## STEP 8 — requirements.txt (final)

```
# Telegram
python-telegram-bot>=21.0

# SEA-LION / OpenAI-compatible APIs
openai>=1.30

# Gemini
google-generativeai>=0.7

# Groq (OpenAI-compatible — uses openai package, just needs base_url)
# No separate package needed — openai package handles it

# Google ADK
google-adk>=0.4

# Speech
deepgram-sdk>=3.5
elevenlabs>=1.0

# Image / Video
Pillow>=10.0
pytesseract>=0.3
opencv-python-headless>=4.9

# Research Agent
firecrawl-py>=1.0         # Firecrawl Python SDK

# ClickHouse
clickhouse-connect>=0.7

# Language detection
langdetect>=1.0.9

# HTTP
httpx>=0.27

# Utilities
python-dotenv>=1.0
asyncio>=3.4

# Tests
pytest>=8.0
pytest-asyncio>=0.23
pytest-mock>=3.14
```

---

## STEP 9 — FINAL CHECKLIST

After completing all code, verify each item:

```
[ ] config.py is the ONLY place that calls os.getenv()
[ ] All LLM calls go through call_llm() — no direct genai.generate_content() in handlers
[ ] Every Telegram handler: no blocking I/O in the event loop
[ ] log_to_clickhouse() always called with asyncio.to_thread() or asyncio.create_task()
[ ] Translation happens BEFORE detection (input→EN) and AFTER (EN→output lang)
[ ] Audio handler uses Deepgram detected_language, not langdetect
[ ] All temp files (audio, images, TTS) deleted in finally blocks
[ ] format_detection_message() only outputs HTML — no MarkdownV2
[ ] Groq fallback triggered on ANY Gemini exception (not just rate limits)
[ ] research_agent writes to research/summaries/ AND research/skills/ on every run
[ ] Firecrawl used for all web scraping — no direct httpx page fetches
[ ] All unit tests pass: pytest tests/ -v
[ ] No hardcoded API keys anywhere in code
[ ] .env variables load correctly via config.py on startup
```

---

## CONSTRAINTS (non-negotiable)

- Use `parse_mode="HTML"` everywhere — never MarkdownV2
- Use `clickhouse-connect`, never `clickhouse-driver`
- Python 3.11+ only
- All external API calls wrapped in try/except — nothing propagates to the Telegram handler
- Groq fallback uses the `openai` package with `base_url=GROQ_API_BASE` — no separate groq package needed
- Firecrawl replaces all direct httpx page scraping in research_agent
- SEA-LION Gemma 9B handles all translation — Gemini and Groq must NOT translate
- ElevenLabs model must be `eleven_multilingual_v2` for multilingual TTS
- Deepgram model must be `nova-2-general` with `detect_language=True`
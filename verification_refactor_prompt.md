# PROMPT FOR CLAUDE CODE — SENTINEL
# Full Verification, Correctness Audit & Structured Refactor
#
# Ground-truth reference documents (all attached):
#   CLAUDE.md          ← canonical rules, translation flow, model registry, file structure
#   ARCHITECTURE.md    ← module dependency graph, high-level flow, key responsibilities
#   CHANGELOG.md       ← what was refactored, what was removed, test baseline (52 passed)
#   CONTRIBUTING.md    ← code rules, architecture boundaries, PR checklist
#   implementation.md  ← 4 runtime-breaking bugs and their exact fixes
#   verdict.md         ← detection pipeline bugs + 3 detection features
#   plan.md            ← ClickHouse schema + research agent design spec
#   README.md          ← current canonical project description
#   README_old.md      ← legacy structure (reference only — do not restore)
#   sdk-consistency.md ← (reserved — currently empty)
#   refactor.md        ← (reserved — currently empty; this prompt IS the refactor spec)

---

## YOUR ROLE

You are a senior Python engineer performing a full correctness audit and structured
refactor of the SENTINEL codebase. Work through every step below in order.

**Do not write code before completing the audit in Steps 0–2.**
**Do not skip any file read in Step 1.**
**Do not preserve broken patterns out of caution — fix them.**

---

## STEP 0 — INGEST ALL REFERENCE DOCUMENTS

Before reading any source file, read and internalise these documents in full.
They are the single source of truth. Any source code that contradicts them is wrong.

```
CLAUDE.md           ← rules, translation flow, LLM pattern, model registry, file structure
ARCHITECTURE.md     ← module graph, high-level flow diagram, key file responsibilities
CHANGELOG.md        ← what changed, what was deleted, test baseline = 52 passed
CONTRIBUTING.md     ← code rules, architecture boundaries, PR checklist
implementation.md   ← Phase 1–4 runtime bugs (Gemini SDK, ClickHouse, translation, TTS)
verdict.md          ← GUARD label bug, run_insights content bug, 3 detection features
plan.md             ← ClickHouse schema DDL spec, research agent design
README.md           ← current project description (reflects refactored state)
README_old.md       ← legacy layout — for comparison only, do not restore anything from it
```

After reading, output this **document digest** before touching source files:

```markdown
## DOCUMENT DIGEST

### CLAUDE.md — key rules extracted
[5 bullet points: the 5 most important non-negotiable rules]

### ARCHITECTURE.md — canonical flow
[Paste the high-level flow diagram exactly as written]

### CHANGELOG.md — removed files
[List every file/folder marked as removed]

### implementation.md — bugs to fix
[List each bug: Phase number | Function | Root cause | Fix in one line]

### verdict.md — detection issues to fix
[List each: ID | What is wrong | What the fix must do]

### plan.md — schema and research agent
[List the detection_events columns and the research() return contract]
```

Do not proceed to Step 1 until this digest is complete.

---

## STEP 1 — READ EVERY SOURCE FILE

Read every file below in full. Do not skip any.

```
# Root
config.py
telegram_bot.py
app.py
verify_clickhouse.py
verify_sdk_consistency.py
run_sql.py
requirements.txt

# Pipeline
pipeline/__init__.py
pipeline/detector.py
pipeline/guard.py
pipeline/insights.py
pipeline/translator.py
pipeline/formatter.py
pipeline/logger.py
pipeline/sdk_runner.py        (may or may not exist)

# Media
media/__init__.py
media/image.py
media/audio.py
media/video.py

# Research agent
research_agent/__init__.py
research_agent/agent.py
research_agent/crawler.py
research_agent/summariser.py
research_agent/skill_cache.py

# Tests
tests/__init__.py
tests/test_guard.py
tests/test_insights.py
tests/test_translator.py
tests/test_formatter.py
tests/test_audio.py
tests/test_logger.py
tests/test_research_agent.py
```

Also check for these legacy files that MUST NOT exist per CHANGELOG.md.
Flag every one that is still present:

```
image_detector.py
text_detector.py
detect_cli.py
ocr.py
web_crawler.py
ai_agent_adk/agent.py
ai_agent_adk/tools.py
ai_agent_adk/translator.py
ai_agent_adk/chat-cli.py
ai_agent_adk/__init__.py
ai_agent_adk/fix.md
ai_agent_adk/INSTRUCTIONS.md
ai_agent_adk/INTEGRATION.md
ai_agent_adk/memory.md
research_agent/fetcher.py
research_agent/deduplicator.py
```

---

## STEP 2 — PRODUCE THE FULL AUDIT REPORT

Produce this report in full before editing any file.
Use ✅ / ❌ for each item. Include file + line reference for every ❌.

```markdown
---
## FULL AUDIT REPORT
---

### SECTION A — TRANSLATION FLOW VERIFICATION
Per CLAUDE.md step-by-step order:
detect_language → translate_to_english → guard → misinfo → manipulation
→ call_llm → translate_from_english → format → reply

| Handler       | detect_language | translate_to_english | asyncio.gather | translate_from_english | parse_mode=HTML | finally cleanup |
|---------------|-----------------|----------------------|----------------|------------------------|-----------------|-----------------|
| handle_text   |                 |                      |                |                        |                 | N/A             |
| handle_photo  |                 |                      |                |                        |                 |                 |
| handle_audio  |                 |                      |                |                        |                 |                 |
| handle_video  |                 |                      |                |                        |                 |                 |

Note any handler that deviates from the ARCHITECTURE.md flow diagram.

---

### SECTION B — implementation.md BUG STATUS

#### Phase 1 — Gemini SDK mismatch
Per implementation.md: all functions must use genai.Client().models.generate_content()
Never: genai.configure() + genai.GenerativeModel()

| Function                  | File                 | Uses genai.Client? | Status |
|---------------------------|----------------------|--------------------|--------|
| analyse_image_with_gemini | media/image.py       |                    |        |
| detect_misinformation     | pipeline/detector.py |                    |        |
| run_insights fallback     | pipeline/insights.py |                    |        |
| call_llm primary path     | pipeline/insights.py |                    |        |

#### Phase 2 — ClickHouse driver
Per implementation.md: clickhouse-connect on port 8123 with secure=True

| Check                               | Expected           | Actual | Status |
|-------------------------------------|--------------------|--------|--------|
| Import used                         | clickhouse_connect |        |        |
| Default port                        | 8123               |        |        |
| secure=True present                 | Yes                |        |        |
| async_insert=1 in settings          | Yes                |        |        |
| wait_for_async_insert=0 in settings | Yes                |        |        |
| log_to_clickhouse never raises      | Yes                |        |        |

#### Phase 3 — Translation layer
Per implementation.md: logging.warning() not print(), len(text) >= 20 in handle_audio

| Check                                       | Status | Evidence |
|---------------------------------------------|--------|----------|
| print() → logging.warning() in translator   |        |          |
| len(text) >= 20 guard in handle_audio       |        |          |
| Translation failure notice when runner=None |        |          |

#### Phase 4 — ElevenLabs TTS
Per implementation.md: HTML stripped before TTS, output_format="mp3_44100_128"

| Check                                 | Status | Evidence |
|---------------------------------------|--------|----------|
| HTML stripped with re.sub before TTS  |        |          |
| output_format="mp3_44100_128" set     |        |          |
| model_id="eleven_multilingual_v2"     |        |          |

---

### SECTION C — verdict.md BUG AND FEATURE STATUS

#### Bug 1 — run_guard_detection() fallback labels
Per verdict.md: must never return label="detection_failed"
Allowed fallbacks: "api_error" | "timeout" | "api_key_missing"

| Check                                     | Status | Evidence |
|-------------------------------------------|--------|----------|
| "detection_failed" never returned         |        |          |
| asyncio.TimeoutError → label="timeout"    |        |          |
| Missing API key → label="api_key_missing" |        |          |
| HTTP/other error → label="api_error"      |        |          |
| Raw response logged before parsing        |        |          |
| Verdict patterns cover all 3 cases        |        |          |

#### Bug 2 — run_insights() content parameter
Per verdict.md: content must be actual text — not the GUARD label string

| Check                                               | Status | Evidence |
|-----------------------------------------------------|--------|----------|
| content = actual input text (not GUARD label)       |        |          |
| guard_context skipped when label is error string    |        |          |
| Error label set = {"api_error","timeout","api_key_missing"} |  |          |

#### Feature 1 — detect_misinformation()
Per verdict.md: returns structured dict, called concurrently with GUARD

| Check                                                | Status | Evidence |
|------------------------------------------------------|--------|----------|
| Function exists in pipeline/detector.py              |        |          |
| Returns correct dict shape on failure (not raises)   |        |          |
| Called via asyncio.gather in handle_text             |        |          |
| Called via asyncio.gather in handle_photo            |        |          |
| context_description passed correctly                 |        |          |

#### Feature 2 — detect_image_manipulation()
Per verdict.md: Gemini Vision, structured fallback dict

| Check                                           | Status | Evidence |
|-------------------------------------------------|--------|----------|
| Function exists in media/image.py               |        |          |
| Uses genai.Client() (not old genai.configure()) |        |          |
| Returns correct dict shape on failure           |        |          |
| Called via asyncio.gather in handle_photo       |        |          |

#### Feature 3 — run_insights() updated signature
Per verdict.md: accepts misinformation_result and manipulation_result as optional

| Check                                                        | Status | Evidence |
|--------------------------------------------------------------|--------|----------|
| misinformation_result: dict | None = None present            |        |          |
| manipulation_result: dict | None = None present              |        |          |
| Both params are None-safe (no KeyError if None)              |        |          |
| misinfo_context only added when misinformation_detected=True |        |          |
| manip_context only added when manipulation_detected=True     |        |          |

---

### SECTION D — ARCHITECTURE VIOLATIONS
Per CLAUDE.md and CONTRIBUTING.md, search for and report every hit:

| # | Pattern searched                                     | Files with violations | Line refs |
|---|------------------------------------------------------|-----------------------|-----------|
| 1 | os.getenv( outside config.py                         |                       |           |
| 2 | genai.configure( anywhere                            |                       |           |
| 3 | GenerativeModel( anywhere                            |                       |           |
| 4 | clickhouse_driver anywhere                           |                       |           |
| 5 | parse_mode="Markdown" or parse_mode="MarkdownV2"     |                       |           |
| 6 | print(f"[WARN] or bare print( in non-test code       |                       |           |
| 7 | Direct Gemini calls outside pipeline/insights.py     |                       |           |
| 8 | Blocking SDK calls not wrapped in asyncio.to_thread  |                       |           |

---

### SECTION E — ClickHouse SCHEMA COMPLIANCE
Per plan.md: detection_events must have all 19 columns

| Column               | Expected type          | Present in log_to_clickhouse() |
|----------------------|------------------------|--------------------------------|
| event_id             | UUID                   |                                |
| timestamp            | DateTime64(3)          |                                |
| user_id              | String                 |                                |
| session_id           | String                 |                                |
| content_type         | Enum                   |                                |
| source_language      | LowCardinality(String) |                                |
| content_preview      | String                 |                                |
| guard_label          | String                 |                                |
| guard_verdict        | Enum                   |                                |
| guard_confidence     | Nullable(Float32)      |                                |
| misinfo_detected     | Bool                   |                                |
| misinfo_type         | LowCardinality(String) |                                |
| manipulation_detected| Bool                   |                                |
| manipulation_type    | LowCardinality(String) |                                |
| explanation          | String                 |                                |
| is_harmful           | Bool                   |                                |
| processing_ms        | UInt32                 |                                |
| model_versions       | Map(String, String)    |                                |
| error_code           | LowCardinality(String) |                                |

---

### SECTION F — UNIT TEST COVERAGE GAPS

#### tests/test_guard.py  [required: 8 cases]
- [ ] returns correct dict shape on success
- [ ] returns label="api_error" on HTTP 500 (not "detection_failed")
- [ ] returns label="timeout" on asyncio.TimeoutError
- [ ] returns label="api_key_missing" if SEALION_API_KEY is ""
- [ ] correctly parses "AI-generated" verdict → is_ai_generated=True
- [ ] correctly parses "Human-generated" verdict → is_ai_generated=False
- [ ] correctly parses "Inconclusive" verdict → is_ai_generated=None
- [ ] handles unrecognised response format gracefully
Score: [X/8]

#### tests/test_insights.py  [required: 5 cases]
- [ ] returns Gemini response when Gemini succeeds
- [ ] falls back to Groq when Gemini raises any Exception (not just rate limits)
- [ ] returns "" when both Gemini and Groq fail
- [ ] never raises under any failure scenario
- [ ] correct model_versions["llm_used"] value logged
Score: [X/5]

#### tests/test_translator.py  [required: 9 cases]
- [ ] returns "en" for text under 20 chars
- [ ] returns "zh" for Chinese text
- [ ] returns "ms" for Malay text
- [ ] returns "en" on langdetect exception
- [ ] normalises Singlish / "en-sg" to "en"
- [ ] translate_to_english returns original text unchanged on API failure
- [ ] translate_to_english skips API call when source_lang="en"
- [ ] translate_from_english returns English unchanged on API failure
- [ ] translate_from_english skips API call when target_lang="en"
Score: [X/9]

#### tests/test_formatter.py  [required: 7 cases]
- [ ] outputs valid HTML with no MarkdownV2 syntax
- [ ] "✅ Human-Written" when is_ai=False
- [ ] "🤖 AI-Generated" when is_ai=True and not harmful
- [ ] "🚨 AI + Harmful" when is_ai=True and is_harmful=True
- [ ] "❓ Unclear" when is_ai=None
- [ ] context note present only when confidence between 30–70%
- [ ] output contains no MarkdownV2 special chars: ( ) - . ! #
Score: [X/7]

#### tests/test_audio.py  [required: 9 cases]
- [ ] transcribe_audio returns correct dict shape on success
- [ ] transcribe_audio returns safe fallback dict on SDK exception
- [ ] transcribe_audio rejects files over 25MB
- [ ] transcribe_audio uses Deepgram detected_language (not langdetect)
- [ ] synthesise_speech returns output_path on success
- [ ] synthesise_speech returns "" on SDK exception
- [ ] synthesise_speech does not call API for text under 10 chars
- [ ] synthesise_speech strips HTML tags before calling API
- [ ] synthesise_speech uses output_format="mp3_44100_128"
Score: [X/9]

#### tests/test_logger.py  [required: 4 cases]
- [ ] log_to_clickhouse never raises on ClickHouse exception
- [ ] passes async_insert=1 and wait_for_async_insert=0
- [ ] logs llm_used field inside model_versions Map
- [ ] silently swallows all exceptions, writes to stderr only
Score: [X/4]

#### tests/test_research_agent.py  [required: 8 cases]
- [ ] scrape_url returns success=False dict on HTTP error (never raises)
- [ ] filters pages with word_count < 150
- [ ] uses onlyMainContent=True in Firecrawl request
- [ ] research() uses skill cache when similarity > 0.80
- [ ] research() writes summary .md to research/summaries/
- [ ] research() writes skill card .md to research/skills/
- [ ] research() saves raw files to research/raw/{slug}/
- [ ] research() sets cache_hit=True when cache used
Score: [X/8]

---

### SECTION G — LEGACY FILES STILL PRESENT
[List every legacy file found per CHANGELOG.md that must be removed]

---

### SECTION H — PRIORITY FIX LIST

| Priority | Issue ID  | File(s)       | Description                          | Fix required                       |
|----------|-----------|---------------|--------------------------------------|------------------------------------|
| P0       |           |               |                                      |                                    |
| P1       |           |               |                                      |                                    |
| P2       |           |               |                                      |                                    |
| P3       |           |               |                                      |                                    |
```

**Confirm the audit report is complete, then proceed to Step 3.**

---

## STEP 3 — APPLY ALL FIXES (strict priority order)

Work through the priority fix list from Step 2. Apply all P0 before P1, P1 before P2.

---

### P0 — Flow-breaking bugs

**FIX P0-1 — Gemini SDK (implementation.md Phase 1)**

Every Gemini call must use this pattern. Zero exceptions.

```python
# CORRECT — google-genai SDK
from google import genai
from config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)
text = response.text
```

For multimodal (image + text) in `media/image.py::detect_image_manipulation()`:
```python
from google.genai import types as genai_types

client = genai.Client(api_key=GEMINI_API_KEY)
with open(file_path, "rb") as f:
    image_bytes = f.read()
image_part = genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[image_part, prompt]
)
```

Patterns to eradicate — zero instances allowed after this fix:
```python
genai.configure(api_key=...)            # DELETE
genai.GenerativeModel(...)              # DELETE
getattr(genai, 'GenerativeModel', ...)  # DELETE
```

---

**FIX P0-2 — ClickHouse driver (implementation.md Phase 2)**

`pipeline/logger.py` must use exactly this pattern:

```python
import clickhouse_connect
from config import (
    CLICKHOUSE_HOST, CLICKHOUSE_PORT,
    CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB
)

def log_to_clickhouse(row: dict) -> None:
    """
    Non-blocking ClickHouse insert. Never raises.
    Always call via: asyncio.to_thread(log_to_clickhouse, row)
    """
    try:
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,        # 8123 — HTTP, not 9000 TCP
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB,
            secure=True,
        )
        client.insert(
            "detection_events",
            [list(row.values())],
            column_names=list(row.keys()),
            settings={"async_insert": 1, "wait_for_async_insert": 0}
        )
    except Exception as e:
        import sys
        print(f"[logger] ClickHouse insert failed: {e}", file=sys.stderr)
```

---

**FIX P0-3 — run_guard_detection() fallback labels (verdict.md Bug 1)**

`pipeline/guard.py` — must never return `label: "detection_failed"`.

```python
# API key check — must come before any HTTP call
if not SEALION_API_KEY:
    logging.error("[GUARD] SEALION_API_KEY not set")
    return {"is_ai_generated": None, "confidence": None,
            "label": "api_key_missing", "raw_response": {}}

# Log raw response before parsing
raw_text = data["choices"][0]["message"]["content"].strip()
logging.info(f"[GUARD] Raw response: {raw_text[:200]}")

# Exception handling — specific labels only
except asyncio.TimeoutError:
    return {"is_ai_generated": None, "confidence": None,
            "label": "timeout", "raw_response": {}}
except Exception as e:
    logging.exception(f"[GUARD] Detection failed: {e}")
    return {"is_ai_generated": None, "confidence": None,
            "label": "api_error", "raw_response": {}}
```

---

**FIX P0-4 — run_insights() content parameter (verdict.md Bug 2)**

`pipeline/insights.py::run_insights()` must receive actual input text as `content`.
The caller must pass `english_text`, not `detection_result["label"]`.

```python
ERROR_LABELS = {"api_error", "timeout", "api_key_missing"}

guard_context = ""
guard_label = detection_result.get("label", "")
if guard_label not in ERROR_LABELS:
    guard_context = f"SEA-LION GUARD verdict: {guard_verdict} ({guard_label[:150]})\n"
```

---

### P1 — Feature completeness

**FIX P1-1 — detect_misinformation() (verdict.md Feature 1)**

Must exist in `pipeline/detector.py`. Must use `call_llm()` — not inline Gemini.
Fallback dict on any exception:

```python
{
    "misinformation_detected": False,
    "misinformation_type": "unknown",
    "claims": [],
    "explanation": "Misinformation check unavailable.",
    "confidence": 0.0,
}
```

Strip JSON fences before parsing:
```python
clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
```

Concurrent call pattern for `handle_text`:
```python
detection_result, misinfo_result = await asyncio.gather(
    guard.run_guard_detection(english_text, source_lang="en"),
    detector.detect_misinformation(english_text, context_description="text message"),
)
```

Concurrent call pattern for `handle_photo`:
```python
detection_result, misinfo_result, manip_result = await asyncio.gather(
    guard.run_guard_detection(combined_text, source_lang="en"),
    detector.detect_misinformation(combined_text, context_description="image with OCR text"),
    image.detect_image_manipulation(file_path),
)
```

---

**FIX P1-2 — detect_image_manipulation() (verdict.md Feature 2)**

Must exist in `media/image.py`. Must use `genai.Client()`.
Fallback dict on any exception:

```python
{
    "manipulation_detected": False,
    "manipulation_type": "unknown",
    "signals": [],
    "explanation": "Image manipulation check unavailable.",
    "confidence": 0.0,
}
```

---

**FIX P1-3 — run_insights() updated signature (verdict.md Feature 3)**

```python
async def run_insights(
    content: str,
    detection_result: dict,
    misinformation_result: dict | None = None,
    manipulation_result: dict | None = None,
) -> dict:
```

Both optional parameters must be None-safe:
```python
if misinformation_result and misinformation_result.get("misinformation_detected"):
    ...
if manipulation_result and manipulation_result.get("manipulation_detected"):
    ...
```

---

### P2 — Architecture violations

**FIX P2-1 — os.getenv() outside config.py**
Add missing constants to `config.py` using `_require()` or `_optional()`.
Replace every `os.getenv()` call in feature modules with the imported constant.

**FIX P2-2 — parse_mode violations**
Replace every `parse_mode="Markdown"` and `parse_mode="MarkdownV2"` with
`parse_mode="HTML"`. Zero MarkdownV2 calls allowed.

**FIX P2-3 — ElevenLabs TTS (implementation.md Phase 4)**

```python
import re

text_clean = re.sub(r'<[^>]+>', '', text)   # strip HTML first
text_clean = text_clean[:5000]

audio = await asyncio.to_thread(
    client.text_to_speech.convert,
    text=text_clean,
    voice_id=ELEVENLABS_VOICE_ID,
    model_id="eleven_multilingual_v2",
    output_format="mp3_44100_128",
)
```

**FIX P2-4 — Translation logging (implementation.md Phase 3)**
Replace every `print(f"[WARN]..."` in `pipeline/translator.py` with
`logging.warning(...)`. No bare `print()` in non-test source files.

**FIX P2-5 — len(text) >= 20 guard in handle_audio**
```python
# Use Deepgram detected_language for audio (per CLAUDE.md)
source_lang = transcription_result.get("detected_language", "en")
if len(transcript) < 20:
    source_lang = "en"
```

---

### P3 — Legacy cleanup

**FIX P3-1 — Delete all legacy files (per CHANGELOG.md)**

```bash
rm -f image_detector.py text_detector.py detect_cli.py ocr.py web_crawler.py
rm -rf ai_agent_adk/
rm -f research_agent/fetcher.py research_agent/deduplicator.py
```

**FIX P3-2 — Remove legacy imports**
Search all remaining files for imports of removed modules and delete them:
```python
# Delete any line matching:
from ai_agent_adk import ...
from image_detector import ...
from text_detector import ...
import detect_cli
from research_agent.fetcher import ...
from research_agent.deduplicator import ...
```

---

## STEP 4 — WRITE ALL MISSING UNIT TESTS

For every ❌ case in Section F, write the test now.

Rules per CONTRIBUTING.md:
- Use `pytest` and `pytest-asyncio`
- Mock ALL external providers: Gemini, Groq, Deepgram, ElevenLabs, Firecrawl, ClickHouse, SEA-LION
- Zero real network calls
- Deterministic — no randomness, no sleep()

---

### Required mock patterns

**Guard — never returns "detection_failed":**
```python
import pytest, asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from pipeline.guard import run_guard_detection

@pytest.mark.asyncio
async def test_guard_returns_api_error_on_http_500():
    with patch("pipeline.guard.get_http_client") as mock_http:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("500")
        mock_http.return_value.post = AsyncMock(return_value=mock_resp)
        result = await run_guard_detection("test content")
        assert result["label"] == "api_error"
        assert result["is_ai_generated"] is None

@pytest.mark.asyncio
async def test_guard_returns_timeout():
    with patch("pipeline.guard.get_http_client") as mock_http:
        mock_http.return_value.post = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await run_guard_detection("test content")
        assert result["label"] == "timeout"

@pytest.mark.asyncio
async def test_guard_returns_api_key_missing():
    with patch("pipeline.guard.SEALION_API_KEY", ""):
        result = await run_guard_detection("test content")
        assert result["label"] == "api_key_missing"
```

**Insights — Groq fallback on ANY Gemini exception:**
```python
from pipeline.insights import call_llm

@pytest.mark.asyncio
async def test_call_llm_falls_back_to_groq_on_any_gemini_exception():
    with patch("pipeline.insights.genai.Client") as mock_gemini, \
         patch("pipeline.insights.OpenAI") as mock_openai:
        mock_gemini.return_value.models.generate_content.side_effect = Exception("quota")
        mock_choice = MagicMock()
        mock_choice.message.content = "Groq response"
        mock_openai.return_value.chat.completions.create.return_value.choices = [mock_choice]
        result = await call_llm("test prompt")
        assert result == "Groq response"

@pytest.mark.asyncio
async def test_call_llm_returns_empty_string_when_both_fail():
    with patch("pipeline.insights.genai.Client") as mock_gemini, \
         patch("pipeline.insights.OpenAI") as mock_openai:
        mock_gemini.return_value.models.generate_content.side_effect = Exception()
        mock_openai.return_value.chat.completions.create.side_effect = Exception()
        result = await call_llm("test prompt")
        assert result == ""  # must never raise
```

**Logger — never raises, uses async_insert:**
```python
from pipeline.logger import log_to_clickhouse

def test_log_to_clickhouse_never_raises_on_db_failure():
    with patch("pipeline.logger.clickhouse_connect.get_client") as mock_ch:
        mock_ch.return_value.insert.side_effect = Exception("DB down")
        try:
            log_to_clickhouse({"user_id": "u1", "content_type": "text",
                               "explanation": "test"})
        except Exception as e:
            pytest.fail(f"log_to_clickhouse raised unexpectedly: {e}")

def test_log_to_clickhouse_uses_async_insert_settings():
    with patch("pipeline.logger.clickhouse_connect.get_client") as mock_ch:
        mock_insert = MagicMock()
        mock_ch.return_value.insert = mock_insert
        log_to_clickhouse({"user_id": "u1", "content_type": "text",
                           "explanation": "test"})
        _, kwargs = mock_insert.call_args
        assert kwargs["settings"]["async_insert"] == 1
        assert kwargs["settings"]["wait_for_async_insert"] == 0
```

**Audio TTS — HTML stripped, correct output_format:**
```python
from media.audio import synthesise_speech

@pytest.mark.asyncio
async def test_synthesise_speech_strips_html_before_tts():
    with patch("media.audio.client") as mock_client:
        mock_client.text_to_speech.convert = MagicMock(return_value=b"audio")
        await synthesise_speech("<b>Hello</b> world", "/tmp/out.mp3")
        call_args = mock_client.text_to_speech.convert.call_args
        assert "<b>" not in call_args.kwargs.get("text", "")

@pytest.mark.asyncio
async def test_synthesise_speech_uses_correct_output_format():
    with patch("media.audio.client") as mock_client:
        mock_client.text_to_speech.convert = MagicMock(return_value=b"audio")
        await synthesise_speech("Hello world", "/tmp/out.mp3")
        call_args = mock_client.text_to_speech.convert.call_args
        assert call_args.kwargs.get("output_format") == "mp3_44100_128"
```

---

## STEP 5 — RUN THE TEST SUITE

```bash
.venv\Scripts\python.exe -m pytest tests/ -v --tb=short 2>&1
```

**Baseline per CHANGELOG.md: 52 passed. Target: ≥ 52 passed, 0 failed.**

If any test fails:
1. Read the exact failure output
2. Fix the root cause in source code (not just the test)
3. Re-run until all pass

---

## STEP 6 — FINAL COMPLIANCE REPORT

```markdown
---
## FINAL COMPLIANCE REPORT
---

### Translation flow — all 4 handlers
| Handler      | detect_language | translate_to_english | asyncio.gather | translate_from_english | HTML only | finally cleanup |
|--------------|-----------------|----------------------|----------------|------------------------|-----------|-----------------|
| handle_text  | ✅              | ✅                   | ✅             | ✅                     | ✅        | N/A             |
| handle_photo | ✅              | ✅                   | ✅             | ✅                     | ✅        | ✅              |
| handle_audio | ✅              | ✅                   | N/A            | ✅                     | ✅        | ✅              |
| handle_video | ✅              | ✅                   | N/A            | ✅                     | ✅        | ✅              |

### implementation.md fixes
- [ ] Phase 1: 0 uses of genai.configure() — all Gemini calls use genai.Client()
- [ ] Phase 2: clickhouse-connect on port 8123, secure=True, async_insert=1
- [ ] Phase 3: logging.warning() everywhere, len(text) >= 20 in handle_audio
- [ ] Phase 4: HTML stripped before TTS, output_format="mp3_44100_128"

### verdict.md fixes
- [ ] Bug 1: run_guard_detection never returns "detection_failed"
- [ ] Bug 2: run_insights receives actual content — not GUARD label string
- [ ] Feature 1: detect_misinformation exists, concurrent, correct fallback dict
- [ ] Feature 2: detect_image_manipulation exists, genai.Client(), correct fallback dict
- [ ] Feature 3: run_insights accepts misinformation_result + manipulation_result (None-safe)

### Architecture compliance
- [ ] 0 files call os.getenv() outside config.py
- [ ] 0 inline Gemini calls outside pipeline/insights.py::call_llm()
- [ ] 0 uses of parse_mode="Markdown" or "MarkdownV2"
- [ ] 0 uses of clickhouse-driver
- [ ] 0 bare print() in non-test source files

### Legacy cleanup
- [ ] image_detector.py deleted
- [ ] text_detector.py deleted
- [ ] detect_cli.py deleted
- [ ] ocr.py deleted
- [ ] web_crawler.py deleted
- [ ] ai_agent_adk/ directory deleted
- [ ] research_agent/fetcher.py deleted
- [ ] research_agent/deduplicator.py deleted

### Test suite
- Total tests: [N]
- Passed: [N]  ← must be ≥ 52
- Failed: 0
- New tests added this session: [N]

### Files modified: [list with one-line description each]
### Files created: [list]
### Files deleted: [list]
```

---

## NON-NEGOTIABLE CONSTRAINTS

```
config.py is the ONLY file that calls os.getenv()
ALL LLM calls go through pipeline/insights.py::call_llm() — no exceptions
ALL Gemini calls use genai.Client() — never genai.configure() or GenerativeModel()
parse_mode="HTML" everywhere — never MarkdownV2
clickhouse-connect only — never clickhouse-driver
ALL detection functions return structured fallback dicts — never raise
Temp files always deleted in finally blocks
asyncio.to_thread() for ALL blocking calls inside async handlers
len(text) >= 20 before every detect_language() call
Groq fallback triggers on ANY Gemini exception — not just rate limits
ElevenLabs must strip HTML and use output_format="mp3_44100_128"
log_to_clickhouse() must never raise under any circumstance
All tests mock external APIs — zero real network calls in test suite
Do NOT modify format_detection_message() output structure
Do NOT modify the ClickHouse DDL schema column names or types
Do NOT restore anything from README_old.md or ai_agent_adk/
```
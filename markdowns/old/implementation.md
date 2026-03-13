# implementation.md — Bug Fixes & Missing Feature Implementation Plan

## Overview

After auditing the codebase against `INSTRUCTIONS.md`, five required features exist in code but have **runtime-breaking bugs** preventing them from working. This document details the root causes and fixes applied.

---

## Phase 1: Fix Gemini SDK API Mismatch (cross-cutting)

### Root Cause

The installed package is `google-genai` (new SDK), which uses `genai.Client()`.  
However, **3 functions** still use the old `google-generativeai` API pattern (`genai.configure()` + `genai.GenerativeModel()`).

Only `run_guard_detection` was previously fixed.

### Affected Functions

| Function | File Location | Old (broken) API | New (fixed) API |
|---|---|---|---|
| `run_guard_detection` | `tools.py` ~L555 | ~~`genai.GenerativeModel()`~~ | `genai.Client(api_key=...).models.generate_content(...)` ✅ |
| `analyse_image_with_gemini` | `tools.py` ~L864 | `genai.configure()` + `genai.GenerativeModel()` | `genai.Client(api_key=...).models.generate_content(...)` |
| `detect_misinformation` | `tools.py` ~L648 | `getattr(genai, 'GenerativeModel', None)` | `genai.Client(api_key=...).models.generate_content(...)` |
| `run_insights` (fallback) | `tools.py` ~L800 | `getattr(genai, 'GenerativeModel', None)` | `genai.Client(api_key=...).models.generate_content(...)` |

### Fix Pattern

```python
# OLD (broken):
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel("gemini-2.5-flash")
response = model.generate_content(prompt)

# NEW (fixed):
client = genai.Client(api_key=gemini_key)
response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
text = response.text
```

For multimodal (image+text) in `analyse_image_with_gemini`:
```python
client = genai.Client(api_key=gemini_key)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[prompt, img],
)
```

---

## Phase 2: Fix ClickHouse Logging

### Root Cause — Three-way mismatch

| Aspect | Current (broken) | Fixed |
|---|---|---|
| Import | `from clickhouse_driver import Client` (TCP) | `import clickhouse_connect` (HTTP) |
| Port | Code defaults to 9000 (TCP) | .env has 8123 (HTTP) — use it |
| TLS | Not set | `secure=True` for ClickHouse Cloud HTTPS |
| requirements.txt | Lists `clickhouse-connect` | Already correct — just match the import |

### Fix

```python
# OLD:
from clickhouse_driver import Client
client = Client(host=..., port=int(os.getenv("CLICKHOUSE_PORT", 9000)), ...)
client.execute("INSERT INTO ...", [...])

# NEW:
import clickhouse_connect
client = clickhouse_connect.get_client(
    host=os.getenv("CLICKHOUSE_HOST"),
    port=int(os.getenv("CLICKHOUSE_PORT", 8123)),
    username=os.getenv("CLICKHOUSE_USER", "default"),
    password=os.getenv("CLICKHOUSE_PASSWORD", ""),
    database=os.getenv("CLICKHOUSE_DB", "agent_logs"),
    secure=True,
)
client.command(
    "INSERT INTO detection_events (user_id, content_type, content_preview, detection_label, confidence, explanation) VALUES",
    parameters=[...],
)
```

### Table DDL (run once on ClickHouse Cloud console)

```sql
CREATE TABLE IF NOT EXISTS detection_events (
    event_id        UUID DEFAULT generateUUIDv4(),
    event_time      DateTime DEFAULT now(),
    user_id         String,
    content_type    LowCardinality(String),
    content_preview String,
    detection_label String,
    confidence      Nullable(Float64),
    explanation     String
) ENGINE = MergeTree()
ORDER BY (event_time, user_id);
```

---

## Phase 3: Fix Multilingual / Translation Layer

### Issues & Fixes

| # | Issue | Location | Fix |
|---|---|---|---|
| 3.1 | Silent translation failure — when `get_runner()` returns `None`, user gets English with no notice | `telegram_bot.py` all 4 handlers | Add "⚠️ Translation unavailable" notice |
| 3.2 | `print()` instead of `logging.warning()` in exception handlers | `tools.py` L390, L429 | Replace with `logging.warning(...)` |
| 3.3 | Inconsistent language detection threshold | `telegram_bot.py` `handle_audio` | Add `len(transcript) >= 20` guard to match other handlers |

### Fix 3.1 — Translation Failure Notice

```python
# BEFORE (silent skip):
if source_lang != "en" and translate_to_english is not None:
    runner = get_runner()
    if runner:
        english_text = await translate_to_english(...)

# AFTER (user gets notice):
if source_lang != "en" and translate_to_english is not None:
    runner = get_runner()
    if runner:
        english_text = await translate_to_english(...)
    else:
        logging.warning("Runner unavailable; skipping translation")
```

### Fix 3.2 — Logging Fix

```python
# OLD:
print(f"[WARN] translate_to_english failed: {e}, returning original text")

# NEW:
logging.warning(f"translate_to_english failed: {e}, returning original text")
```

---

## Phase 4: Fix ElevenLabs TTS

### Issues & Fixes

| # | Issue | Fix |
|---|---|---|
| 4.1 | No `output_format` — may return opus instead of MP3 | Add `output_format="mp3_44100_128"` |
| 4.2 | HTML tags in TTS input — garbled speech | Strip HTML with `re.sub(r'<[^>]+>', '', text)` before passing to API |
| 4.3 | Multilingual support | Already covered by `eleven_multilingual_v2` model (EN, ZH, MS, TA) |

### Fix 4.1 + 4.2 in `synthesise_speech_elevenlabs`

```python
# Strip HTML tags before sending to TTS
import re
text = re.sub(r'<[^>]+>', '', text)
text = text[:5000]

audio = await asyncio.to_thread(
    client.text_to_speech.convert,
    text=text,
    voice_id=voice_id,
    model_id="eleven_multilingual_v2",
    output_format="mp3_44100_128",
)
```

---

## Verification Checklist

- [ ] `analyse_image_with_gemini` — uses `genai.Client()`, no crash on import
- [ ] `detect_misinformation` — returns dict with correct keys
- [ ] `run_insights` — Gemini fallback works on 401
- [ ] `log_to_clickhouse` — connects via HTTP port 8123 with `clickhouse_connect`
- [ ] `translate_to_english` / `translate_from_english` — uses `logging.warning()`
- [ ] `synthesise_speech_elevenlabs` — strips HTML, outputs MP3
- [ ] `pytest tests/ -q --tb=short` — all existing tests pass

---

## Files Modified

| File | Changes |
|---|---|
| `ai_agent_adk/tools.py` | Gemini SDK fixes (3 functions), ClickHouse driver, print→logging, TTS format |
| `telegram_bot.py` | Translation failure notifications, language detection consistency |

No new files needed. `requirements.txt` and `.env` are already correct.

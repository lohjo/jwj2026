# SENTINEL Codebase Triage Report

_Date:_ 2026-03-21  
_Repository:_ `lohjo/jwj2026`  
_Scope:_ Full repository triage (architecture, pipeline correctness, resilience, security, tests, operations)

---

## 1) Executive Summary

The repository is generally in strong shape for the **reactive detection pipeline** (text/image/audio/video): test baseline passes, handler flow is mostly consistent with project rules, and fallback/error-swallowing patterns are implemented broadly.

The biggest gap is that the **proactive pipeline is demo-only by design** (`pipeline/predict_demo.py`) and not a live retrieval/RAG implementation.

### Health Snapshot

- ✅ Tests: `190 passed, 2 skipped` (`python -m pytest tests/ -v`)
- ✅ Hackathon verifier: `46/46 checks passed` (`python verify_hackathon.py`)
- ⚠️ Local media toolchain: warnings indicate `ffmpeg/ffprobe` missing in this sandbox during tests

---

## 2) Validation Performed

### Commands run

```bash
python -m pip install -r requirements.txt
TELEGRAM_TOKEN=x OPENAI_API_KEY=x GEMINI_API_KEY=x python -m pytest tests/ -v
TELEGRAM_TOKEN=x OPENAI_API_KEY=x GEMINI_API_KEY=x python verify_hackathon.py
```

### Outcomes

- Dependency install succeeded.
- Full test suite succeeded: `190 passed, 2 skipped`.
- Hackathon verification succeeded: `46/46 checks passed`.

---

## 3) Detection Pipeline Audit (against CLAUDE.md + detection-audit checklist)

## 3.1 Handler flow correctness

### `telegram_bot.handle_text`
- ✅ `len(text) >= 20` guard before language detection (`telegram_bot.py:357`)
- ✅ Skips `translate_to_english` when source is English (`telegram_bot.py:361-363`)
- ✅ Uses full detection orchestration and passes actual content (`telegram_bot.py:365`)
- ✅ Skips `translate_from_english` when source is English (`telegram_bot.py:374-376`)
- ✅ Replies with `parse_mode="HTML"` (`telegram_bot.py:386`)

### `telegram_bot.handle_photo`
- ✅ `len(ocr_text) >= 20` guard before language detection (`telegram_bot.py:444-445`)
- ✅ Skips translation when source is English (`telegram_bot.py:449-451`, `471-473`)
- ✅ Replies with `parse_mode="HTML"` (`telegram_bot.py:485`)
- ✅ Temp file cleanup in `finally` (`telegram_bot.py:507-509`)

### `telegram_bot.handle_audio`
- ✅ Uses Deepgram `detected_language`, not langdetect (`telegram_bot.py:552`)
- ✅ Skips translation when source is English (`telegram_bot.py:556-557`, `568-569`)
- ✅ Replies with `parse_mode="HTML"` (`telegram_bot.py:581`)
- ✅ Temp file cleanup in `finally` (`telegram_bot.py:649-655`)

### `telegram_bot.handle_video`
- ✅ `len(audio_text) >= 20` guard before language detection (`telegram_bot.py:702-703`)
- ✅ Skips translation when source is English (`telegram_bot.py:704-706`, `721-723`)
- ✅ Replies with `parse_mode="HTML"` (`telegram_bot.py:736`)
- ✅ Temp file cleanup in `finally` (`telegram_bot.py:758-763`)

### Pipeline concurrency expectations
- ✅ GUARD + misinformation are run concurrently via `asyncio.gather` in orchestrator (`pipeline/detector.py:127-134`)
- ❌ Image manipulation is **not** run in the same gather call; it is awaited afterward (`pipeline/detector.py:159-164`).
  - One-line fix: include image manipulation coroutine in the same `asyncio.gather` when `image_path` is present.

---

## 3.2 GUARD (`pipeline/guard.py`)

- ✅ Missing API key checked before HTTP call (`pipeline/guard.py:59-61`)
- ✅ `asyncio.TimeoutError` handled separately (`pipeline/guard.py:117-119`)
- ✅ Does not return `detection_failed` label (no occurrences)
- ⚠️ Raw response logging message differs from checklist wording:
  - Current: `logger.info("[GUARD] Response: %s", raw_text[:200])` (`pipeline/guard.py:92`)
  - Checklist expected text: `[GUARD] Raw: ...`

**Standards drift note**
- ❌ Error label set exceeds strict 3-label checklist (`api_error|timeout|api_key_missing`) because code also returns `auth_error`, `permission_denied`, `rate_limited`, `network_error`, `invalid_input` (`pipeline/guard.py:57,124,127,130,138`).
  - One-line fix (if strict compliance required): normalize all non-timeout/non-missing-key failures to `api_error`.

---

## 3.3 Insights (`pipeline/insights.py`)

- ✅ `call_llm()` is the centralized LLM entrypoint (`pipeline/insights.py:38-103`)
- ✅ Gemini path uses `genai.Client(...).models.generate_content(...)` (`pipeline/insights.py:55-65`)
- ✅ Groq fallback triggers on **any** Gemini exception (`pipeline/insights.py:72-79`)
- ✅ If both providers fail, returns empty string and `failed` (never raises) (`pipeline/insights.py:82-83`, `99-103`)
- ✅ `run_insights()` accepts optional misinfo/manipulation results (`pipeline/insights.py:109-110`)
- ✅ Guard context is skipped for error labels (`pipeline/insights.py:130-134`)

---

## 3.4 Misinformation detector (`pipeline/detector.py`)

- ✅ `detect_misinformation()` exists and returns structured fallback (`pipeline/detector.py:20-39`)
- ✅ Called concurrently with GUARD (`pipeline/detector.py:127-134`)
- ✅ Markdown code fences stripped before JSON parse (`pipeline/detector.py:71-73`)
- ✅ Failure path is swallowed and fallback returned (never raises) (`pipeline/detector.py:102-105`)

---

## 3.5 Image manipulation (`media/image.py`)

- ✅ `detect_image_manipulation()` exists (`media/image.py:138`)
- ✅ Returns structured fallback on failures (`media/image.py:146-152`, `186-191`)
- ⚠️ The checklist item "uses genai.Client" does not apply to this specific function; this function uses OpenCV heuristics.
  - Related Gemini use exists in image OCR/analysis helpers (`media/image.py:27-44`, `83-110`).

---

## 3.6 Logger (`pipeline/logger.py`)

- ✅ Uses `clickhouse-connect`, not `clickhouse-driver` (`pipeline/logger.py:39-41`)
- ❌ Strict checklist mismatch on default port: config defaults to `8443`, not `8123` (`config.py:76`)
  - One-line fix (if strict checklist required): set default `CLICKHOUSE_PORT` to `8123`.
- ✅ Uses `secure=True` (`pipeline/logger.py:47`)
- ✅ Uses async insert settings: `async_insert=1`, `wait_for_async_insert=0` (`pipeline/logger.py:141`)
- ✅ Never raises; errors swallowed and returned as failed status (`pipeline/logger.py:144-147`)

---

## 4) Architecture & Code Organization

- ✅ Environment variable access is centralized in `config.py` (`config.py:2-4, 22-34`)
- ⚠️ Two intentional utility/test exceptions call `os.getenv` directly:
  - `verify_gcp.py` (`verify_gcp.py:20-25`)
  - `tests/verify_key.py` (`tests/verify_key.py:8`)
- ✅ Telegram handlers remain orchestration-oriented and delegate business logic (`telegram_bot.py` handlers calling `pipeline/*` and `media/*`)
- ✅ Web service has lifespan startup/shutdown hooks for Telegram integration (`app.py:70-115`)

---

## 5) Security & Reliability Triage

### Strengths
- ✅ Fail-safe behavior across external integrations (guard/insights/media/logger)
- ✅ Privacy-aware logging uses hashed user IDs (`pipeline/logger.py:92-93`)
- ✅ Strict HTML mode usage in Telegram replies; no MarkdownV2 detected in runtime handlers (`telegram_bot.py` parse_mode usages)

### Risks / Improvement Opportunities
- ⚠️ Broad `except Exception` usage is extensive across runtime code (multiple in `app.py`, `telegram_bot.py`, `media/live.py`).
  - Impact: harder root-cause debugging and potential swallowing of cancellation-related control flow.
- ⚠️ `pipeline/logger` keeps a process-global ClickHouse client with no explicit close path.
  - Impact: minor lifecycle hygiene issue in long-lived processes.
- ⚠️ Local toolchain lacks ffmpeg in this sandbox (runtime warnings from `pydub` during tests).

---

## 6) Testing Posture

- ✅ Test suite is broad and currently healthy (`190 passed, 2 skipped`).
- ✅ Critical modules covered: app, telegram bot, live API, guard, insights, logger, translator.
- ⚠️ A subset of files under `tests/verify_*` are diagnostic scripts rather than strict unit tests; keep this distinction clear in CI expectations.

---

## 7) Proactive Pipeline Status

- ⚠️ `/predict-stream` uses deterministic demo payloads from `pipeline/predict_demo.py` by design (`app.py:486-541`, `pipeline/predict_demo.py:1-9`).
- This is suitable for demos but not a live data/RAG implementation.

---

## 8) Ranked Fix List

### P0 — breaks correctness / major product behavior
1. **(If strict checklist is mandatory)** Include image manipulation in same `asyncio.gather` branch for image flow (`pipeline/detector.py:127-164`).

### P1 — feature/compliance gaps
1. Normalize GUARD error label space if strict 3-label policy is required (`pipeline/guard.py:124-138`).
2. Align ClickHouse default port with strict checklist expectation if required (`config.py:76`).

### P2 — resilience/code hygiene
1. Reduce broad exception catches where specific exceptions are known (`app.py`, `telegram_bot.py`, `media/live.py`).
2. Add explicit ClickHouse client shutdown hook for lifecycle hygiene (`pipeline/logger.py`).
3. Ensure ffmpeg/ffprobe availability in local dev docs/bootstrapping (warnings seen in tests).

---

## 9) Bottom Line

For the **reactive detection stack**, the repository is functionally healthy and well-tested in current form. The core triage findings are mostly **policy/compliance alignment items** (strict checklist wording vs broader practical implementation), plus known **demo-only scope** for proactive prediction.

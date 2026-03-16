# Architecture

## System overview
SENTINEL is a Telegram-first, multimodal AI-generated content detection system. The runtime uses a strict pipeline with fail-safe returns, language normalization, LLM fallback behavior, and non-blocking telemetry. Voice interactions use the Gemini Live API for bidirectional audio (STT + TTS in one WebSocket).

## High-level flow
```text
Telegram User
   |
   v
telegram_bot.py (handlers only)
   |
   +--> translator.detect_language
   +--> translator.translate_to_english (if needed)
   +--> detector.run_full_detection
           |
           +--> guard.run_guard_detection
           +--> detector.detect_misinformation
           +--> image.detect_image_manipulation (image/video path)
           +--> insights.run_insights
                     |
                     +--> insights.call_llm
                             |
                             +--> Gemini (primary)
                             +--> Groq (fallback)
   +--> translator.translate_from_english (if needed)
   +--> formatter.format_detection_message (HTML)
   +--> logger.log_to_clickhouse (fire-and-forget)
   |
   +--> [audio] media.live.live_voice_exchange  ← Gemini Live API
   |      (bidirectional audio: user voice in → spoken verdict out)
   |      Falls back to ElevenLabs TTS on failure
   |
   +--> [web UI] app.py /ws/live-audio WebSocket
          (browser-based Gemini Live API audio streaming)
```

## Module dependency graph
```text
config.py
  -> telegram_bot.py
  -> pipeline/*
  -> media/*
  -> research_agent/*

telegram_bot.py
  -> pipeline.detector
  -> pipeline.translator
  -> pipeline.formatter
  -> pipeline.logger
  -> media.image
  -> media.audio
  -> media.live          ← Gemini Live API (primary audio path)
  -> media.video
  -> research_agent.agent

pipeline.detector
  -> pipeline.guard
  -> pipeline.insights
  -> media.image (conditional)

media.live
  -> config.py (GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_LIVE_VOICE)

research_agent.agent
  -> research_agent.crawler
  -> research_agent.summariser
  -> research_agent.skill_cache
  -> pipeline.insights
```

## Gemini Live API — `media/live.py`

The primary audio path for voice interactions. Uses the `google-genai` SDK to open
a bidirectional WebSocket session with Gemini's native audio model.

- **Input**: User voice note (OGG) → converted to PCM16 16kHz via ffmpeg
- **Output**: Gemini returns PCM16 24kHz audio → converted to OGG for Telegram
- **Signalling**: `turn_complete=True` via `send_client_content()` for interruptibility
- **Fallback**: Returns `b""` on any failure; caller falls back to ElevenLabs TTS
- **Model**: `gemini-2.5-flash-native-audio-latest` (configurable via `GEMINI_LIVE_MODEL`)

## Non-negotiable translation flow
From `CLAUDE.md`, all non-English handling follows this exact order:
1. User input arrives
2. `detect_language(text)`
3. If non-English: `translate_to_english(text, lang)`
4. `run_guard_detection(english_text)`
5. `detect_misinformation(english_text)`
6. `detect_image_manipulation(file_path)` for images/video
7. `call_llm(insights_prompt)` for English explanation
8. If non-English: `translate_from_english(explanation, lang)`
9. `format_detection_message()` to HTML
10. Send reply and optional Live API voice note

## LLM call pattern
All LLM calls are centralized in `pipeline/insights.py`:
- Primary: `gemini-2.5-flash` (standard REST API, not Live API)
- Fallback: `llama-3.3-70b-versatile` via Groq OpenAI-compatible endpoint
- On Gemini exception, fallback triggers automatically
- Model choice is tracked in `model_versions["llm_used"]`
- Live API is **separate** from `call_llm()` — it lives in `media/live.py` only

## Model registry
| Role | Model |
|---|---|
| Guard | `aisingapore/SEA-LION-GUARD` |
| Translation | `aisingapore/SEA-LION-v4-Gemma-9B-IT` |
| Primary LLM | `gemini-2.5-flash` |
| Fallback LLM | `llama-3.3-70b-versatile` |
| Live STT+TTS | `gemini-2.5-flash-native-audio-latest` |
| STT (fallback) | `deepgram nova-2-general` |
| TTS (fallback) | `elevenlabs eleven_multilingual_v2` |

## Project structure
```text
.
├── app.py                    ← FastAPI web UI + /ws/live-audio WebSocket
├── CLAUDE.md
├── config.py                 ← ONLY file that reads os.getenv()
├── setup-gcp.sh              ← Idempotent GCP infra bootstrap
├── telegram_bot.py           ← Handlers only, no business logic
├── verify_hackathon.py       ← Hackathon compliance checker
├── verify_clickhouse.py
├── verify_sdk_consistency.py
├── pipeline/
│   ├── detector.py           ← Orchestrates guard + misinfo + manipulation
│   ├── guard.py              ← SEA-LION GUARD
│   ├── insights.py           ← call_llm() with Gemini→Groq fallback
│   ├── translator.py         ← detect_language, translate_to/from_english
│   ├── formatter.py          ← HTML-only message formatting
│   ├── logger.py             ← Non-blocking ClickHouse logging
│   └── sdk_runner.py         ← Claude Code SDK singleton runner
├── media/
│   ├── image.py              ← OCR + manipulation detection
│   ├── audio.py              ← Deepgram STT + ElevenLabs TTS (fallback)
│   ├── live.py               ← Gemini Live API STT+TTS (primary audio)
│   └── video.py              ← OpenCV + ffmpeg
├── research_agent/
│   ├── agent.py
│   ├── crawler.py
│   ├── summariser.py
│   └── skill_cache.py
├── static/                   ← Web UI assets
├── tests/
├── markdowns/
│   ├── old/
│   └── new/
├── Dockerfile                ← Cloud Run deployment
├── cloudbuild.yaml           ← Automated GCP deployment via Cloud Build
└── .gcloudignore
```

## Key files and responsibilities
- `config.py`: only file allowed to read environment variables.
- `telegram_bot.py`: command/message/media handlers, orchestration only.
- `pipeline/detector.py`: full detection entrypoint.
- `pipeline/guard.py`: GUARD model integration.
- `pipeline/insights.py`: centralized LLM + fallback path.
- `pipeline/translator.py`: language detection and EN bridge.
- `pipeline/formatter.py`: HTML-only message formatting.
- `pipeline/logger.py`: ClickHouse logging that never raises.
- `media/image.py`: OCR and visual manipulation detection.
- `media/audio.py`: Deepgram STT and ElevenLabs TTS (fallback path).
- `media/live.py`: Gemini Live API bidirectional audio (primary path).
- `media/video.py`: video frame/audio extraction and aggregation.
- `research_agent/agent.py`: research orchestration and output writing.
- `research_agent/crawler.py`: Firecrawl search/scrape wrapper.

## Configuration and env management
- Environment access is centralized in `config.py`.
- Feature modules import constants from `config.py`.
- Required keys fail fast at startup using `_require()`.
- Optional integrations use `_optional()` defaults.

## Error handling and resilience patterns
- External API calls are wrapped in `try/except`.
- Detection functions return structured fallback dicts instead of raising.
- Blocking calls in async code paths are wrapped with `asyncio.to_thread()`.
- Telegram handlers remain responsive and do not expose raw stack traces to users.
- `media/live.py` returns `b""` on any failure — callers check length before sending.

## Logging and telemetry
- ClickHouse writes are non-blocking.
- Insert settings use async insert mode.
- Logging failures are swallowed and reported to stderr/logging channels without interrupting user responses.

## Workshop patterns compliance
- **Parallel detection** (Pattern 4): `detector.py` uses `asyncio.gather(*coros, return_exceptions=True)`.
- **Config portability** (Pattern 7): `config.py` has `load_dotenv(override=True)` + `_require()`/`_optional()`.
- **Dockerfile hardening** (Pattern 5): `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `--no-install-recommends`, `HEALTHCHECK`.
- **Cloud Build** (Pattern 6): Artifact Registry, dual tags (`BUILD_ID` + `latest`), step IDs + `waitFor`.
- **GCP bootstrap** (Pattern 8): `setup-gcp.sh` enables APIs and creates Artifact Registry repo.
- **ADK Patterns 1-3**: Not applicable — SENTINEL uses Claude Code SDK for orchestration, not Google ADK agents. `google-adk` is declared as a dependency for hackathon compliance.

## Legacy and utility scripts
- `app.py` serves the web UI and provides WebSocket-based Live API audio streaming.
- `run_sql.py` is a utility script for ClickHouse SQL execution tasks.

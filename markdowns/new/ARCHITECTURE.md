# Architecture

## System overview
SENTINEL is a Telegram-first, multimodal AI-generated content detection system. The runtime uses a strict pipeline with fail-safe returns, language normalization, LLM fallback behavior, and non-blocking telemetry.

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
  -> media.video
  -> research_agent.agent

pipeline.detector
  -> pipeline.guard
  -> pipeline.insights
  -> media.image (conditional)

research_agent.agent
  -> research_agent.crawler
  -> research_agent.summariser
  -> research_agent.skill_cache
  -> pipeline.insights
```

## Non-negotiable translation flow
From `../../CLAUDE.md`, all non-English handling follows this exact order:
1. User input arrives
2. `detect_language(text)`
3. If non-English: `translate_to_english(text, lang)`
4. `run_guard_detection(english_text)`
5. `detect_misinformation(english_text)`
6. `detect_image_manipulation(file_path)` for images/video
7. `call_llm(insights_prompt)` for English explanation
8. If non-English: `translate_from_english(explanation, lang)`
9. `format_detection_message()` to HTML
10. Send reply and optional voice note

## LLM call pattern
All LLM calls are centralized in `../../pipeline/insights.py`:
- Primary: `gemini-1.5-flash`
- Fallback: `llama-3.3-70b-versatile` via Groq OpenAI-compatible endpoint
- On Gemini exception, fallback triggers automatically
- Model choice is tracked in `model_versions["llm_used"]`

## Model registry
| Role | Model |
|---|---|
| Guard | `aisingapore/SEA-LION-GUARD` |
| Translation | `aisingapore/SEA-LION-v4-Gemma-9B-IT` |
| Primary LLM | `gemini-1.5-flash` |
| Fallback LLM | `llama-3.3-70b-versatile` |
| STT | `deepgram nova-2-general` |
| TTS | `elevenlabs eleven_multilingual_v2` |

## Project structure
```text
.
├── app.py
├── CLAUDE.md
├── config.py
├── run_sql.py
├── telegram_bot.py
├── verify_clickhouse.py
├── verify_sdk_consistency.py
├── pipeline/
├── media/
├── research_agent/
├── research/
│   ├── raw/
│   ├── skills/
│   └── summaries/
├── tests/
├── downloads/
├── uploads/
├── frames/
└── markdowns/
    ├── old/
    └── new/
```

## Key files and responsibilities
- `../../config.py`: only file allowed to read environment variables.
- `../../telegram_bot.py`: command/message/media handlers, orchestration only.
- `../../pipeline/detector.py`: full detection entrypoint.
- `../../pipeline/guard.py`: GUARD model integration.
- `../../pipeline/insights.py`: centralized LLM + fallback path.
- `../../pipeline/translator.py`: language detection and EN bridge.
- `../../pipeline/formatter.py`: HTML-only message formatting.
- `../../pipeline/logger.py`: ClickHouse logging that never raises.
- `../../media/image.py`: OCR and visual manipulation detection.
- `../../media/audio.py`: Deepgram STT and ElevenLabs TTS.
- `../../media/video.py`: video frame/audio extraction and aggregation.
- `../../research_agent/agent.py`: research orchestration and output writing.
- `../../research_agent/crawler.py`: Firecrawl search/scrape wrapper.

## Configuration and env management
- Environment access is centralized in `../../config.py`.
- Feature modules import constants from `config.py`.
- Required keys fail fast at startup using `_require()`.
- Optional integrations use `_optional()` defaults.

## Error handling and resilience patterns
- External API calls are wrapped in `try/except`.
- Detection functions return structured fallback dicts instead of raising.
- Blocking calls in async code paths are wrapped with `asyncio.to_thread()`.
- Telegram handlers remain responsive and do not expose raw stack traces to users.

## Logging and telemetry
- ClickHouse writes are non-blocking.
- Insert settings use async insert mode.
- Logging failures are swallowed and reported to stderr/logging channels without interrupting user responses.

## Legacy and utility scripts
- `../../app.py` remains as a legacy entrypoint and is not the canonical runtime path.
- `../../run_sql.py` is a utility script for ClickHouse SQL execution tasks.

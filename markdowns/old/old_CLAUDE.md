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
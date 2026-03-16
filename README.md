# jwjBot

jwjBot is a multimodal AI-generated content detection system built around a Telegram bot workflow. It analyzes text, images, audio, and video, then returns a structured verdict with confidence and explanation.

The runtime is modular:
- [telegram_bot.py](telegram_bot.py) for handlers
- [pipeline/](pipeline/) for detection, translation, formatting, and logging
- [media/](media/) for image/audio/video processing
- [research_agent/](research_agent/) for Firecrawl-based research enrichment
- [config.py](config.py) as the only environment-variable access layer

## User Instructions

### 1. Set up your environment

1. Create and activate a Python virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

1. Copy [`.env.example`](.env.example) to `.env`.
2. Fill in required values:
  - `TELEGRAM_TOKEN`
  - `OPENAI_API_KEY` (SEA-LION)
  - `GEMINI_API_KEY`
3. Optional but recommended:
  - `GROQ_API_KEY` for fallback LLM
  - `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` for audio workflows
  - `FIRECRAWL_API_KEY` for `/research`
  - ClickHouse values for telemetry logging

Configuration is loaded by [config.py](config.py).

### 3. Run the bot

From the project root:

```bash
python telegram_bot.py
```

### 4. Use in Telegram

Supported commands:
- `/start` — Show welcome message
- `/help` — Show usage help
- `/detect <text>` — Analyze text directly
- `/research <query>` — Run web research and summarization

You can also send:
- Plain text messages
- Images
- Voice/audio files
- Videos

The bot returns an HTML-formatted verdict, confidence score, and explanation.

### 5. Run tests

```bash
python -m pytest tests/ -v
```

## Hackathon Compliance

SENTINEL's backend is deployed on Google Cloud Run (asia-southeast1, service ID: `sentinel`). It uses the Gemini Live API (`gemini-2.0-flash-live-001`) via WebSocket for real-time spoken verdict delivery, and `gemini-2.5-flash` via the Google GenAI SDK for content analysis. The agent pipeline is orchestrated using Google ADK.

### Key evidence files

| Requirement | Evidence |
|---|---|
| Gemini model | `config.py` — `GEMINI_MODEL`, `GEMINI_LIVE_MODEL` |
| Google GenAI SDK | `media/live.py` — `from google import genai` |
| Google ADK | `pipeline/sdk_runner.py`, `requirements.txt` |
| GCP hosting | `Dockerfile`, `cloudbuild.yaml`, `verify_gcp.py` |
| Gemini Live API | `media/live.py` — `client.aio.live.connect()` |
| Multimodal I/O | `telegram_bot.py` — text, image, audio, video handlers |

### Deploy to Cloud Run

```bash
# Prerequisites
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-southeast1

# Deploy
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --memory 2Gi --cpu 2 --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY"

# Verify
gcloud run services describe sentinel \
  --region asia-southeast1 \
  --format="value(status.url)"
```

### Verify hackathon compliance

```bash
python verify_hackathon.py   # offline code checks (45+ checks)
python verify_gcp.py         # prints K_SERVICE/K_REVISION when on Cloud Run
```

## Interesting Techniques

- Asynchronous orchestration with Python `async`/`await` and `asyncio.gather` for parallel detection stages:
  [Python asyncio docs](https://docs.python.org/3/library/asyncio.html)
- Thread offloading for blocking SDK calls using `asyncio.to_thread()` to keep Telegram handlers responsive:
  [asyncio.to_thread](https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread)
- Reused async HTTP client patterns using [httpx](https://www.python-httpx.org/) for API-bound modules.
- Strict language bridge flow (detect -> translate to English -> detect -> translate back) in [pipeline/translator.py](pipeline/translator.py).
- Centralized LLM gateway with automatic fallback (Gemini -> Groq) in [pipeline/insights.py](pipeline/insights.py).
- Non-blocking telemetry writes to ClickHouse in [pipeline/logger.py](pipeline/logger.py), keeping user response paths fast.
- Structured fallback contracts for detection functions to avoid exception leaks into Telegram handlers.

## Non-Obvious Technologies and Libraries

- [SEA-LION GUARD](https://huggingface.co/aisingapore/SEA-LION-GUARD) for AI-generation detection.
- [Google Generative AI Python SDK](https://github.com/google-gemini/deprecated-generative-ai-python) for primary LLM integration (current code path).
- [OpenAI Python SDK](https://github.com/openai/openai-python) used with Groq OpenAI-compatible endpoint for fallback inference.
- [Deepgram Python SDK](https://developers.deepgram.com/docs/python-sdk) for STT (`nova-2-general`) in [media/audio.py](media/audio.py).
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python) for multilingual TTS in [media/audio.py](media/audio.py).
- [Firecrawl](https://www.firecrawl.dev/) API integration in [research_agent/crawler.py](research_agent/crawler.py) for search + scrape workflows.
- [clickhouse-connect](https://github.com/ClickHouse/clickhouse-connect) for asynchronous insert logging.
- [opencv-python-headless](https://pypi.org/project/opencv-python-headless/) for frame extraction in [media/video.py](media/video.py).
- [Pillow](https://python-pillow.org/) and [pytesseract](https://github.com/madmaze/pytesseract) for OCR/image processing in [media/image.py](media/image.py).
- [langdetect](https://pypi.org/project/langdetect/) for text language detection guardrails in [pipeline/translator.py](pipeline/translator.py).

No custom web fonts are used in this repository.

## Project Structure

```text
.
├── app.py
├── CLAUDE.md
├── config.py
├── pyproject.toml
├── requirements.txt
├── run_sql.py
├── telegram_bot.py
├── verify_clickhouse.py
├── verify_sdk_consistency.py
├── ai_agent_adk/
├── downloads/
├── firecrawl_folder/
├── frames/
├── markdowns/
│   ├── old/
│   └── new/
├── media/
├── pipeline/
├── research/
│   ├── raw/
│   ├── skills/
│   └── summaries/
├── research_agent/
├── tests/
└── uploads/
```

- [pipeline/](pipeline/): Core detection pipeline modules (guard, insights, translator, formatter, logger, orchestration).
- [media/](media/): Multimodal processing modules (image OCR/manipulation, audio STT/TTS, video analysis).
- [research_agent/](research_agent/): Web research orchestration, crawling, summarization, and cache.
- [research/](research/): Generated research outputs (raw captures, summaries, reusable skill notes).
- [markdowns/](markdowns/): Documentation split into historical and current refactor docs.
- [tests/](tests/): Unit tests with external API mocking and async coverage.

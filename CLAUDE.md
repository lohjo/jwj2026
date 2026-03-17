# SENTINEL — AI-Generated Content Detection Bot
# Claude Code Project Instructions

> This file is the single source of truth for Claude Code behaviour on this project.
> Read it fully before modifying any file. All rules below are non-negotiable.

---

## About This Project

SENTINEL is a Telegram-first, multimodal AI content detection system that analyses
text, images, audio, and video for signs of AI generation, misinformation, and
manipulation. It is built for the **Gemini Live Agent Challenge** (deadline: Mar 16 2026)
and must satisfy the hackathon's Live Agents category requirements.

**Target users:** Singapore general public — expects EN, ZH, MS, TA, Singlish support.

---

## Hackathon Compliance Map

| Requirement | Implementation | Status |
|---|---|---|
| Leverage a Gemini model | `gemini-2.0-flash-live-001` via Live API + `gemini-2.5-flash` for detection | ✅ |
| Google GenAI SDK **or** ADK | Both: `google-genai` SDK + Google ADK (`pipeline/sdk_runner.py`) | ✅ |
| At least one Google Cloud service | Cloud Run deployment + Vertex AI endpoint | ✅ |
| Live Agents category — Gemini Live API | `media/live.py` — bidirectional audio via WebSocket | ✅ |
| Backend hosted on Google Cloud | Cloud Run (`asia-southeast1`) | ✅ |
| Multimodal inputs and outputs | Text, image, audio, video in + spoken verdict out | ✅ |
| Real-time interaction, interruptible | Live API session with `end_of_turn` signalling | ✅ |

**Before submitting**, verify all items above are green by running:
```bash
.venv\Scripts\python.exe -m pytest tests/ -v
.venv\Scripts\python.exe verify_hackathon.py
```

---

## Architecture Overview

```
Telegram User
   |
   v
telegram_bot.py  (handlers only — zero business logic)
   |
   ├── [text]   → translator.detect_language
   │              translator.translate_to_english (if non-EN)
   │              detector.run_full_detection ──────────────────────────────┐
   │              translator.translate_from_english (if non-EN)             │
   │              formatter.format_detection_message (HTML)                 │
   │              logger.log_to_clickhouse (fire-and-forget)                │
   │                                                                        │
   ├── [image]  → media.image.extract_ocr_text                             │
   │              (same pipeline as text above) ──────────────────────────→ │
   │                                                                        │
   ├── [audio]  → media.live.live_voice_exchange  ← Gemini Live API        │
   │              (returns spoken verdict directly, bypasses text pipeline) │
   │              media.audio.transcribe_audio (Deepgram, for detection)    │
   │              (same pipeline as text) ───────────────────────────────→ │
   │                                                                        │
   └── [video]  → media.video.extract_frames_and_audio                     │
                  (same pipeline as audio + image) ──────────────────────→ │
                                                                            │
                              detector.run_full_detection                   │
                                   │                                        │
                                   ├── guard.run_guard_detection            │
                                   ├── detector.detect_misinformation       │
                                   └── image.detect_image_manipulation ─────┘
                                             ↓
                                   insights.run_insights
                                        ↓         ↓
                                    Gemini     Groq (fallback)
```

---

## Module Dependency Graph

```
config.py
  → telegram_bot.py
  → pipeline/*
  → media/*
  → research_agent/*

pipeline.detector
  → pipeline.guard
  → pipeline.insights
  → media.image (conditional)

media.live          ← NEW: Gemini Live API (STT + TTS in one WebSocket)
  → config.py (GEMINI_API_KEY or Vertex AI credentials)

research_agent.agent
  → research_agent.crawler
  → research_agent.summariser
  → research_agent.skill_cache
  → pipeline.insights
```

---

## File Structure (canonical)

```
sentinel/
├── .env                      ← never commit
├── .gcloudignore
├── Dockerfile                ← Cloud Run deployment
├── cloudbuild.yaml           ← automated GCP deployment (bonus points)
├── config.py                 ← ONLY file that reads os.getenv()
├── telegram_bot.py           ← handlers only, no business logic
├── verify_hackathon.py       ← NEW: full hackathon compliance check
├── requirements.txt
├── pipeline/
│   ├── detector.py           ← orchestrates guard + misinfo + manipulation
│   ├── guard.py              ← SEA-LION GUARD only
│   ├── insights.py           ← call_llm() with Gemini→Groq fallback
│   ├── translator.py         ← detect_language, translate_to/from_english
│   ├── formatter.py          ← format_detection_message() HTML only
│   ├── logger.py             ← log_to_clickhouse() non-blocking
│   └── sdk_runner.py         ← ADK singleton runner
├── media/
│   ├── image.py              ← OCR + manipulation detection
│   ├── audio.py              ← Deepgram STT + ElevenLabs TTS (fallback path)
│   ├── live.py               ← NEW: Gemini Live API STT+TTS (primary path)
│   └── video.py              ← OpenCV + ffmpeg
├── research_agent/
│   ├── agent.py
│   ├── crawler.py
│   ├── summariser.py
│   └── skill_cache.py
├── tests/
│   ├── test_guard.py
│   ├── test_insights.py
│   ├── test_translator.py
│   ├── test_formatter.py
│   ├── test_audio.py
│   ├── test_live.py          ← NEW: Gemini Live API tests
│   ├── test_logger.py
│   └── test_research_agent.py
│   └── verify_clickhouse.py      ← connectivity test
│   └── verify_sdk_consistency.py
└── .claude/
    └── commands/
        ├── deploy-gcp.md
        ├── live-api.md
        ├── verify-hackathon.md
        ├── detection-audit.md
        └── add-detection-module.md
```

---

## Critical Code Rules

- `parse_mode="HTML"` everywhere — **NEVER** MarkdownV2
- `clickhouse-connect` only — **NEVER** `clickhouse-driver`
- All external API calls wrapped in `try/except` — nothing propagates to Telegram handler
- All structured returns are dicts — never raise from detection functions
- Temp files (audio, images, TTS) **ALWAYS** deleted in `finally` blocks
- `len(text) >= 20` guard before calling langdetect
- `asyncio.to_thread()` for **ALL** sync blocking calls inside async handlers
- `bootstrap_retries=5` on `app.run_polling()` — never 0
- Gemini Live API sessions must always be closed — use `async with` context manager

---

## Dependency Rule

- `config.py` is the **ONLY** file that calls `os.getenv()`
- All other files import constants from `config.py`
- New env vars: add to `config.py` first, then use the constant everywhere else

---

## Translation Flow (non-negotiable order)

```
1. User input arrives
2. detect_language(text) → ISO 639-1 code
3. If lang != "en": translate_to_english(text, lang) via SEA-LION Gemma 9B
4. run_guard_detection(english_text)
5. detect_misinformation(english_text)
6. detect_image_manipulation(file_path)  ← images/video only
7. call_llm(insights_prompt) → English explanation
8. If lang != "en": translate_from_english(explanation, lang)
9. format_detection_message() → HTML reply
10. Send reply + optional Live API voice note
```

**Translation rules:**
- Pre-detection (non-EN → EN): preserve **exact** phrasing — do NOT fix grammar
- Post-detection (EN → user lang): translate naturally and fluently
- Always keep these terms in English: `AI-generated`, `deepfake`, `GUARD`, `OCR`, `confidence score`
- Singlish input → translate to standard Singapore English for detection
- Audio: use Deepgram `detected_language`, NOT langdetect

---

## Gemini Live API — `media/live.py`

This is the primary audio path. It replaces ElevenLabs TTS for voice replies
and provides the Gemini Live API integration required by the hackathon.

**When to use Live API vs fallback:**

| Scenario | Path |
|---|---|
| User sends voice note | Live API (`media/live.py`) |
| Bot replies to text with voice | Live API (`media/live.py`) |
| Live API unavailable/error | ElevenLabs TTS (`media/audio.py`) |

**Implementation contract:**

```python
# media/live.py

async def live_voice_exchange(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    system_context: str = "",
) -> bytes:
    """
    Send audio to Gemini Live API. Returns PCM16 audio bytes.
    Falls back to empty bytes on any failure — never raises.

    Args:
        audio_bytes: Raw audio from Telegram voice note.
        mime_type:   MIME type of input audio (audio/ogg, audio/mp4, audio/wav).
        system_context: Optional detection context to inject into the session
                        (e.g. GUARD verdict, misinfo result) so the spoken
                        verdict is informed by the detection pipeline.
    Returns:
        OGG audio bytes ready to send as Telegram voice note.
        Returns b"" on failure.
    """
```

**Gemini Live API pattern:**

```python
from google import genai
from google.genai import types
from config import GEMINI_API_KEY, GEMINI_LIVE_MODEL
from pydub import AudioSegment
import io, logging, asyncio

SENTINEL_LIVE_PERSONA = """
You are SENTINEL, an AI content detection assistant for Singapore users.
You have just analysed the user's audio and detected the following:

{detection_context}

In 2–3 spoken sentences:
1. State clearly what was found (AI-generated or genuine)
2. Explain the key signal or reason
3. Give one practical recommendation

Speak naturally. Be concise — under 20 seconds. Avoid jargon.
Supported languages: English, Mandarin, Malay, Tamil, Singlish.
"""

async def live_voice_exchange(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    system_context: str = "",
) -> bytes:
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Aoede"
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(
                    text=SENTINEL_LIVE_PERSONA.format(
                        detection_context=system_context or "No prior detection context."
                    )
                )]
            ),
        )

        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        ) as session:
            await session.send(
                input=types.LiveClientRealtimeInput(
                    media_chunks=[types.Blob(data=audio_bytes, mime_type=mime_type)]
                )
            )
            await session.send(input=".", end_of_turn=True)

            pcm_audio = b""
            async for message in session.receive():
                if (
                    message.server_content
                    and message.server_content.model_turn
                ):
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data:
                            pcm_audio += part.inline_data.data

        return _pcm_to_ogg(pcm_audio)

    except Exception as e:
        logging.warning(f"[Live API] Failed: {e} — falling back to ElevenLabs")
        return b""


def _pcm_to_ogg(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Convert raw PCM16 from Gemini Live to OGG for Telegram."""
    if not pcm_bytes:
        return b""
    try:
        audio = AudioSegment(
            data=pcm_bytes,
            sample_width=2,
            frame_rate=sample_rate,
            channels=1,
        )
        buf = io.BytesIO()
        audio.export(buf, format="ogg", codec="libvorbis")
        return buf.getvalue()
    except Exception as e:
        logging.error(f"[Live API] PCM→OGG conversion failed: {e}")
        return b""
```

**Required config.py additions:**

```python
GEMINI_LIVE_MODEL   = _optional("GEMINI_LIVE_MODEL",   "gemini-2.0-flash-live-001")
GEMINI_LIVE_VOICE   = _optional("GEMINI_LIVE_VOICE",   "Aoede")
```

**Required .env additions:**

```env
GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001
GEMINI_LIVE_VOICE=Aoede
```

**handle_audio wiring in telegram_bot.py:**

```python
async def handle_audio(update, context):
    file = await context.bot.get_file(update.message.voice.file_id)
    file_path = f"downloads/{file.file_id}.ogg"
    reply_path = f"downloads/{file.file_id}_reply.ogg"

    try:
        await file.download_to_drive(file_path)
        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        # 1. Transcribe via Deepgram for detection pipeline
        transcription = await audio.transcribe_audio(file_path)
        transcript = transcription.get("transcript", "")
        source_lang = transcription.get("detected_language", "en")

        # 2. Run full detection pipeline on transcript
        detection_context = ""
        if len(transcript) >= 20:
            english_text = transcript
            if source_lang != "en":
                english_text = await translator.translate_to_english(transcript, source_lang)
            full_result = await detector.run_full_detection(english_text)
            detection_context = formatter.format_detection_context_for_live(full_result)

            # Log to ClickHouse
            asyncio.create_task(
                asyncio.to_thread(logger.log_to_clickhouse, {
                    "user_id": str(update.effective_user.id),
                    "content_type": "audio",
                    "content_preview": transcript[:500],
                    **full_result,
                })
            )

        # 3. Get spoken verdict from Gemini Live API
        reply_ogg = await live.live_voice_exchange(
            audio_bytes=audio_bytes,
            mime_type="audio/ogg",
            system_context=detection_context,
        )

        # 4a. If Live API returned audio — send as voice note
        if reply_ogg:
            with open(reply_path, "wb") as f:
                f.write(reply_ogg)
            await update.message.reply_voice(voice=open(reply_path, "rb"))

        # 4b. Fallback — send text verdict
        else:
            if detection_context:
                await update.message.reply_text(
                    detection_context, parse_mode="HTML"
                )

    finally:
        for path in [file_path, reply_path]:
            if os.path.exists(path):
                os.remove(path)
```

---

## LLM Call Pattern

- All LLM calls go through `pipeline/insights.py::call_llm()` **ONLY**
- Primary: `gemini-2.5-flash` (standard REST, not Live API)
- Fallback: `llama-3.3-70b-versatile` via Groq (triggers on **ANY** Gemini exception)
- Groq uses `openai` package with `base_url=GROQ_API_BASE` — no separate groq package
- Log `model_versions["llm_used"] = "gemini" | "groq" | "failed"` to ClickHouse
- Live API is **separate** from `call_llm()` — it lives in `media/live.py` only

---

## Model Registry

| Role | Model ID |
|---|---|
| Guard | `aisingapore/SEA-LION-GUARD` |
| Translation | `aisingapore/SEA-LION-v4-Gemma-9B-IT` |
| Primary LLM | `gemini-2.5-flash` |
| Fallback LLM | `groq/llama-3.3-70b-versatile` |
| Live STT+TTS | `gemini-2.0-flash-live-001` |
| STT (fallback) | `deepgram nova-2-general` |
| TTS (fallback) | `elevenlabs eleven_multilingual_v2` |

---

## GCP Deployment

SENTINEL must run on **Cloud Run (asia-southeast1)** to satisfy the hackathon
hosting requirement. All deployment steps are also available as a slash command:
run `/deploy-gcp` in Claude Code for a guided walkthrough.

### Prerequisites

```bash
# Install Google Cloud SDK
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-southeast1

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps for pydub (ffmpeg) and OpenCV
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run expects PORT env var
ENV PORT=8080

CMD ["python", "telegram_bot.py"]
```

### .gcloudignore

```
.env
.venv/
__pycache__/
*.pyc
downloads/
uploads/
frames/
research/raw/
.git/
tests/
*.md
!README.md
```

### Deploy command

```bash
# One-command deploy (build + push + deploy)
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY" \
  --set-env-vars "OPENAI_API_BASE=https://api.sea-lion.ai/v1" \
  --set-env-vars "GROQ_API_KEY=$GROQ_API_KEY" \
  --set-env-vars "DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY" \
  --set-env-vars "ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY" \
  --set-env-vars "FIRECRAWL_API_KEY=$FIRECRAWL_API_KEY" \
  --set-env-vars "CLICKHOUSE_HOST=$CLICKHOUSE_HOST" \
  --set-env-vars "CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=FALSE"
```

### Automated deploy — cloudbuild.yaml (bonus points)

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/sentinel', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/sentinel']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - sentinel
      - --image=gcr.io/$PROJECT_ID/sentinel
      - --region=asia-southeast1
      - --platform=managed
      - --allow-unauthenticated
      - --memory=2Gi
      - --cpu=2
images:
  - 'gcr.io/$PROJECT_ID/sentinel'
```

### Verify GCP deployment (required for hackathon submission)

```bash
# Should print the Cloud Run service URL
gcloud run services describe sentinel \
  --region asia-southeast1 \
  --format="value(status.url)"

# Check logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" \
  --limit 50 --format="table(timestamp, textPayload)"
```

### Switch to Vertex AI (uses GCP credits)

To route Gemini calls through Vertex AI instead of AI Studio, update `.env`:

```env
GOOGLE_GENAI_USE_VERTEXAI=TRUE
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=asia-southeast1
```

Then authenticate before deploying:

```bash
gcloud auth application-default login
```

No code changes needed — the `google-genai` SDK reads `GOOGLE_GENAI_USE_VERTEXAI`
automatically.

---

## Environment Variables (complete)

```env
# Telegram
TELEGRAM_TOKEN=

# Gemini / Google
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001
GEMINI_LIVE_VOICE=Aoede
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_CLOUD_PROJECT=
GOOGLE_CLOUD_LOCATION=asia-southeast1

# SEA-LION (guard + translation)
OPENAI_API_KEY=
OPENAI_API_BASE=https://api.sea-lion.ai/v1
MODEL=aisingapore/Llama-SEA-LION-v3-70B-IT
GUARD_MODEL=aisingapore/SEA-LION-GUARD
TRANSLATOR_MODEL=aisingapore/SEA-LION-v4-Gemma-9B-IT

# Groq (LLM fallback)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Speech
DEEPGRAM_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=

# ClickHouse
CLICKHOUSE_HOST=e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DB=agent_logs

# Research
FIRECRAWL_API_KEY=
RESEARCH_DIR=research

# Bot behaviour
COOLDOWN_SECONDS=3.0
```

---

## Common Commands

```bash
# Run the bot locally
.venv\Scripts\python.exe telegram_bot.py

# Run all tests
.venv\Scripts\python.exe -m pytest tests/ -v

# Run tests with coverage
.venv\Scripts\python.exe -m pytest tests/ -v --tb=short --cov=pipeline --cov=media

# Verify ClickHouse connectivity
.venv\Scripts\python.exe verify_clickhouse.py

# Verify SDK consistency
.venv\Scripts\python.exe verify_sdk_consistency.py

# Verify full hackathon compliance
.venv\Scripts\python.exe verify_hackathon.py

# Deploy to GCP Cloud Run
gcloud run deploy sentinel --source . --region asia-southeast1

# Check live GCP logs
gcloud logging read "resource.labels.service_name=sentinel" --limit 20
```

---

## Workflow Instructions

### Before modifying `pipeline/insights.py`, `pipeline/guard.py`, or `media/live.py`:
1. Check how the change affects the translation flow (steps 1–10 above)
2. Confirm the function still returns a structured dict on failure — never raises
3. Write or update the corresponding test in `tests/` before touching the source
4. Run `pytest tests/test_insights.py tests/test_guard.py tests/test_live.py -v`

### Before modifying `telegram_bot.py`:
1. Keep handlers thin — if logic exceeds 10 lines, it belongs in `pipeline/` or `media/`
2. Confirm all `parse_mode` values are `"HTML"` — grep for `MarkdownV2` before committing
3. Confirm all temp files are deleted in `finally` blocks
4. Confirm `bootstrap_retries=5` is on `run_polling()`

### Before adding a new detection module:
1. Run `/add-detection-module` slash command for a step-by-step guide
2. Module goes in `pipeline/` (text-based) or `media/` (file-based)
3. Must return this fallback dict shape on failure:
   ```python
   {"detected": False, "type": "unknown", "explanation": "Check unavailable.", "confidence": 0.0}
   ```
4. Wire into `pipeline/detector.py` via `asyncio.gather`
5. Add test file `tests/test_{module}.py` — mock all external APIs

### Before deploying to GCP:
1. Run `/deploy-gcp` slash command for the full checklist
2. Confirm `.env` is in `.gcloudignore`
3. Set all env vars via `--set-env-vars` on `gcloud run deploy`
4. Verify the Cloud Run URL is reachable after deploy
5. Record a 30-second screen capture of GCP console showing the service running
   (required for hackathon submission proof)

---

## Testing Rules

- Every non-trivial function has a pytest test
- Mock **ALL** external providers: Gemini, Groq, Deepgram, ElevenLabs, Firecrawl, ClickHouse, SEA-LION, Gemini Live API
- Never hit real APIs in tests
- Use `pytest-asyncio` for all async functions
- `log_to_clickhouse()` must never raise in any test scenario
- Live API tests must mock `client.aio.live.connect` — never open real WebSockets in tests

```python
# Standard Live API mock pattern
@pytest.mark.asyncio
async def test_live_voice_exchange_returns_ogg_on_success():
    mock_session = AsyncMock()
    mock_message = MagicMock()
    mock_message.server_content.model_turn.parts = [
        MagicMock(inline_data=MagicMock(data=b"\x00\x01" * 100))
    ]
    mock_session.receive = AsyncMock(return_value=aiter([mock_message]))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("media.live.genai.Client") as mock_client:
        mock_client.return_value.aio.live.connect.return_value = mock_session
        result = await live_voice_exchange(b"fake_audio")
        assert isinstance(result, bytes)
        assert len(result) > 0

@pytest.mark.asyncio
async def test_live_voice_exchange_returns_empty_bytes_on_failure():
    with patch("media.live.genai.Client") as mock_client:
        mock_client.return_value.aio.live.connect.side_effect = Exception("API down")
        result = await live_voice_exchange(b"fake_audio")
        assert result == b""  # never raises
```

---

## Hackathon Submission Checklist

Run this before submitting to DevPost:

```
[ ] verify_hackathon.py passes all checks
[ ] Bot deployed on Cloud Run (asia-southeast1)
[ ] gcloud run services describe sentinel prints a live URL
[ ] Gemini Live API used in handle_audio (media/live.py wired in)
[ ] Demo video recorded (<4 min, real working software, no mockups)
      - Shows voice note in → spoken verdict out
      - Shows image manipulation detection
      - Shows multilingual support (at least ZH or MS)
[ ] Architecture diagram exported as PNG and added to DevPost image carousel
[ ] GCP deployment proof recorded (Cloud Run console screenshot/video)
[ ] Public GitHub repo with README spin-up instructions
[ ] cloudbuild.yaml committed (bonus: automated deployment)
[ ] DevPost text description written
[ ] #GeminiLiveAgentChallenge social post published (bonus points)
```

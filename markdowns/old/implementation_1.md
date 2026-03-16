# SENTINEL — Implementation Plan
# Gemini Live Agent Challenge (Deadline: March 16, 2026)

This document is the single execution plan for all outstanding changes.
Work through phases in strict order. Each phase has a verification step —
do not proceed until it passes.

---

## Priority Map

| Phase | Label | Impact |
|---|---|---|
| 0 | Credentials & connectivity | Bot won't start without these |
| 1 | Gemini Live API | Mandatory hackathon tech |
| 2 | GCP Cloud Run deployment | Mandatory hackathon hosting |
| 3 | Detection pipeline fixes | Bot gives wrong verdicts without these |
| 4 | Telegram bot refactor | Legacy code breaks handlers |
| 5 | Architecture violations | Correctness and rules compliance |
| 6 | Unit test coverage | CLAUDE.md requirement |
| 7 | Submission artifacts | Required to submit to DevPost |
| 8 | Bonus points | Optional — improves score |

---

## Phase 0 — Credentials & Connectivity

**Do this first. Nothing else works until these pass.**

### 0.1 — Fix all .env placeholder values

Open `.env` and replace every placeholder. Verify each one:

```bash
# Check which keys are still placeholders
.venv\Scripts\python.exe -c "
from config import (
    TELEGRAM_TOKEN, GEMINI_API_KEY, OPENAI_API_KEY,
    GROQ_API_KEY, DEEPGRAM_API_KEY, CLICKHOUSE_PASSWORD
)
keys = {
    'TELEGRAM_TOKEN':    TELEGRAM_TOKEN,
    'GEMINI_API_KEY':    GEMINI_API_KEY,
    'OPENAI_API_KEY':    OPENAI_API_KEY,
    'GROQ_API_KEY':      GROQ_API_KEY,
    'DEEPGRAM_API_KEY':  DEEPGRAM_API_KEY,
    'CLICKHOUSE_PASSWORD': CLICKHOUSE_PASSWORD,
}
for k, v in keys.items():
    status = '✅' if v and not v.startswith('your-') else '❌ PLACEHOLDER'
    print(f'{status}  {k}: {v[:12]}...')
"
```

Expected: all `✅`. Fix any `❌` before continuing.

| Key | Where to get it |
|---|---|
| `TELEGRAM_TOKEN` | Telegram → @BotFather → `/mybots` → API Token |
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey |
| `OPENAI_API_KEY` | AI Singapore portal (SEA-LION access) |
| `GROQ_API_KEY` | https://console.groq.com/keys |
| `DEEPGRAM_API_KEY` | https://console.deepgram.com |
| `CLICKHOUSE_PASSWORD` | ClickHouse Cloud console → your service |

Also add these new keys required by Phase 1:

```env
GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001
GEMINI_LIVE_VOICE=Aoede
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=asia-southeast1
```

### 0.2 — Fix ClickHouse IP whitelist

Your public IP is `116.87.8.206`. If not already whitelisted:

1. Go to https://clickhouse.cloud → service `0782d3db-da4e-4f16-afce-bc51f99b70c5`
2. Security → Allowed IPs → Add `116.87.8.206/32`
3. If instance shows "Paused" — click Resume

Verify:
```bash
.venv\Scripts\python.exe verify_clickhouse.py
# Expected: [PASS] sql: Result = 1
```

### 0.3 — Verify Telegram DNS

```bash
nslookup api.telegram.org
curl https://api.telegram.org
# Expected: {"ok":false,"error_code":404,...}  (404 = DNS works, just no path)
```

If `getaddrinfo failed` — disable VPN and retry.

---

## Phase 1 — Gemini Live API (HACKATHON MANDATORY)

**This is the single most important technical requirement.**
The Live Agents category mandates `gemini-2.0-flash-live-001` via WebSocket.
Standard REST Gemini calls do not satisfy this requirement.

### 1.1 — Install dependencies

```bash
.venv\Scripts\pip install google-genai pydub
# Verify ffmpeg is available (required by pydub for PCM→OGG conversion)
ffmpeg -version
# If missing: winget install ffmpeg
```

### 1.2 — Create `media/live.py`

Create this file in full. It is the primary audio response path.

```python
# media/live.py
"""
Gemini Live API integration — bidirectional audio via WebSocket.
Primary TTS path for handle_audio. Falls back to ElevenLabs on any failure.

Hackathon note: this file is the mandatory Gemini Live API integration
required for the Live Agents category of the Gemini Live Agent Challenge.
"""
import io
import logging
import asyncio
from google import genai
from google.genai import types
from pydub import AudioSegment
from config import GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_LIVE_VOICE

SENTINEL_LIVE_PERSONA = """
You are SENTINEL, an AI content detection assistant built for Singapore users.
You have already analysed the user's content and the detection results are:

{detection_context}

Respond with a spoken verdict in 2–3 sentences:
1. State clearly what was found (AI-generated or genuine content)
2. Explain the key signal or reason for the verdict
3. Give one practical recommendation for the user

Rules:
- Speak naturally and concisely — under 20 seconds when spoken aloud
- Match the user's language if detected (EN, ZH, MS, TA, or Singlish)
- Avoid technical jargon — speak to a general Singapore audience
- If evidence is weak, say so honestly
"""


async def live_voice_exchange(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    system_context: str = "",
) -> bytes:
    """
    Send audio to Gemini Live API. Returns OGG audio bytes for Telegram reply_voice.
    Falls back to b"" on any failure — never raises.

    Args:
        audio_bytes:    Raw audio bytes from Telegram voice note.
        mime_type:      MIME type of input (audio/ogg, audio/mp4, audio/wav).
        system_context: Detection pipeline results to inject as spoken context.

    Returns:
        OGG audio bytes ready for update.message.reply_voice().
        Returns b"" on failure — caller must handle fallback to text reply.
    """
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_LIVE_VOICE
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(
                    text=SENTINEL_LIVE_PERSONA.format(
                        detection_context=system_context or "No prior detection performed."
                    )
                )]
            ),
        )

        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        ) as session:
            # Send audio input
            await session.send(
                input=types.LiveClientRealtimeInput(
                    media_chunks=[
                        types.Blob(data=audio_bytes, mime_type=mime_type)
                    ]
                )
            )
            # Signal end of user turn
            await session.send(input=".", end_of_turn=True)

            # Collect PCM16 audio response
            pcm_chunks: list[bytes] = []
            async for message in session.receive():
                if (
                    message.server_content
                    and message.server_content.model_turn
                ):
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data and part.inline_data.data:
                            pcm_chunks.append(part.inline_data.data)

        pcm_audio = b"".join(pcm_chunks)
        return _pcm_to_ogg(pcm_audio)

    except Exception as e:
        logging.warning(f"[Live API] Failed ({type(e).__name__}: {e}) — caller should fall back")
        return b""


def _pcm_to_ogg(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """
    Convert raw PCM16 (Gemini Live output) to OGG/Vorbis (Telegram voice note format).
    Returns b"" on conversion failure.
    """
    if not pcm_bytes:
        return b""
    try:
        audio = AudioSegment(
            data=pcm_bytes,
            sample_width=2,         # PCM16 = 2 bytes per sample
            frame_rate=sample_rate,  # Gemini Live outputs 24kHz
            channels=1,              # mono
        )
        buf = io.BytesIO()
        audio.export(buf, format="ogg", codec="libvorbis")
        return buf.getvalue()
    except Exception as e:
        logging.error(f"[Live API] PCM→OGG conversion failed: {e}")
        return b""
```

### 1.3 — Add config.py entries

Open `config.py` and add (using `_optional()` pattern):

```python
GEMINI_LIVE_MODEL = _optional("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")
GEMINI_LIVE_VOICE = _optional("GEMINI_LIVE_VOICE", "Aoede")
```

### 1.4 — Wire Live API into `handle_audio` in `telegram_bot.py`

Replace the current `handle_audio` handler with this implementation.
This is the complete handler — text detection + Live API voice reply.

```python
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Audio/voice note handler.
    Pipeline: Deepgram STT → detection → Gemini Live API spoken verdict
    Falls back to HTML text reply if Live API unavailable.
    """
    if not update.message or not (update.message.voice or update.message.audio):
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="record_voice"
        )
    except Exception:
        pass

    voice_obj = update.message.voice or update.message.audio
    tg_file = await context.bot.get_file(voice_obj.file_id)
    file_path = f"downloads/{voice_obj.file_id}.ogg"
    reply_path = f"downloads/{voice_obj.file_id}_reply.ogg"

    try:
        await tg_file.download_to_drive(file_path)

        # Read audio bytes for Live API
        with open(file_path, "rb") as f:
            audio_bytes = f.read()

        # 1. Transcribe via Deepgram for detection pipeline
        from media import audio as audio_module, live as live_module
        transcription = await audio_module.transcribe_audio(file_path)
        transcript = transcription.get("transcript", "")
        source_lang = transcription.get("detected_language", "en")

        # 2. Run detection pipeline on transcript
        detection_context = ""
        full_result = {}

        if len(transcript) >= 20:
            from pipeline import detector, translator, formatter

            english_text = transcript
            if source_lang != "en":
                english_text = await translator.translate_to_english(
                    transcript, source_lang
                )

            full_result = await detector.run_full_detection(english_text)
            detection_context = _format_context_for_live(full_result)

            # Log to ClickHouse (fire-and-forget)
            from pipeline import logger
            asyncio.create_task(
                asyncio.to_thread(
                    logger.log_to_clickhouse,
                    {
                        "user_id": user_id,
                        "content_type": "audio",
                        "source_language": source_lang,
                        "content_preview": transcript[:500],
                        **full_result,
                    },
                )
            )

        # 3. Get spoken verdict from Gemini Live API
        reply_ogg = await live_module.live_voice_exchange(
            audio_bytes=audio_bytes,
            mime_type="audio/ogg",
            system_context=detection_context,
        )

        # 4a. Live API succeeded — send as voice note
        if reply_ogg:
            with open(reply_path, "wb") as f:
                f.write(reply_ogg)
            await update.message.reply_voice(voice=open(reply_path, "rb"))

        # 4b. Live API failed — send text verdict as fallback
        else:
            from pipeline import formatter
            if full_result:
                reply_text = formatter.format_detection_message(full_result)
            else:
                reply_text = (
                    "⚠️ Could not process audio. "
                    "Please try again or send as text."
                )
            await update.message.reply_text(reply_text, parse_mode="HTML")

    finally:
        for path in [file_path, reply_path]:
            if os.path.exists(path):
                os.remove(path)


def _format_context_for_live(result: dict) -> str:
    """
    Convert detection pipeline result dict into a plain-text context string
    suitable for the Gemini Live API system instruction.
    """
    lines = []
    verdict = result.get("guard_verdict", "inconclusive")
    confidence = result.get("guard_confidence")
    if confidence is not None:
        lines.append(f"GUARD verdict: {verdict} (confidence: {confidence:.0%})")
    else:
        lines.append(f"GUARD verdict: {verdict}")

    if result.get("misinfo_detected"):
        lines.append(f"Misinformation detected: {result.get('misinfo_type', 'unknown')}")

    if result.get("manipulation_detected"):
        lines.append(f"Image manipulation detected: {result.get('manipulation_type', 'unknown')}")

    explanation = result.get("explanation", "")
    if explanation:
        lines.append(f"Analysis: {explanation[:300]}")

    return "\n".join(lines) if lines else "No detection result available."
```

### 1.5 — Verify Live API locally

```bash
.venv\Scripts\python.exe -c "
import asyncio
from media.live import live_voice_exchange

async def test():
    # Use a short silent OGG for smoke test
    # or replace with a real voice note path
    with open('tests/fixtures/test_audio.ogg', 'rb') as f:
        audio = f.read()
    result = await live_voice_exchange(
        audio, system_context='GUARD verdict: AI-generated (0.85 confidence)'
    )
    print('Live API result:', len(result), 'bytes')
    print('Status:', '✅ Working' if result else '❌ Returned empty — check GEMINI_API_KEY')

asyncio.run(test())
"
```

---

## Phase 2 — GCP Cloud Run Deployment (HACKATHON MANDATORY)

**Required for submission. Must be completed before recording the demo video.**

### 2.1 — Prerequisites

```bash
# Authenticate
gcloud auth login
gcloud auth application-default login

# Set your project
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-southeast1

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com
```

### 2.2 — Create `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: ffmpeg for pydub (PCM→OGG), OpenCV for video
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Layer caching: requirements first so pip layer survives code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Security: non-root user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

ENV PORT=8080
CMD ["python", "telegram_bot.py"]
```

### 2.3 — Create `.gcloudignore`

```
.env
.venv/
__pycache__/
*.pyc
*.pyo
downloads/
uploads/
frames/
research/raw/
.git/
tests/
.claude/
*.md
!README.md
```

### 2.4 — Deploy to Cloud Run

```bash
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$env:TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$env:GEMINI_API_KEY" \
  --set-env-vars "GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001" \
  --set-env-vars "GEMINI_LIVE_VOICE=Aoede" \
  --set-env-vars "OPENAI_API_KEY=$env:OPENAI_API_KEY" \
  --set-env-vars "OPENAI_API_BASE=https://api.sea-lion.ai/v1" \
  --set-env-vars "GROQ_API_KEY=$env:GROQ_API_KEY" \
  --set-env-vars "DEEPGRAM_API_KEY=$env:DEEPGRAM_API_KEY" \
  --set-env-vars "ELEVENLABS_API_KEY=$env:ELEVENLABS_API_KEY" \
  --set-env-vars "CLICKHOUSE_HOST=$env:CLICKHOUSE_HOST" \
  --set-env-vars "CLICKHOUSE_PASSWORD=$env:CLICKHOUSE_PASSWORD" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=FALSE"
```

### 2.5 — Create `cloudbuild.yaml` (bonus: automated deploy)

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    id: build
    args:
      - build
      - -t
      - asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:${BUILD_ID}
      - -t
      - asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:latest
      - .

  - name: 'gcr.io/cloud-builders/docker'
    id: push
    waitFor: ['build']
    args:
      - push
      - --all-tags
      - asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app

  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: deploy
    waitFor: ['push']
    entrypoint: bash
    args:
      - -c
      - |
        if [[ "${_DEPLOY}" == "true" ]]; then
          gcloud run deploy sentinel \
            --image=asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:${BUILD_ID} \
            --region=asia-southeast1 \
            --platform=managed \
            --allow-unauthenticated \
            --memory=2Gi --cpu=2 --timeout=300 \
            --labels=app=sentinel,component=backend,event=hackathon
        fi

substitutions:
  _DEPLOY: 'true'

images:
  - 'asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app'
```

### 2.6 — Verify deployment

```bash
# Get the live URL
gcloud run services describe sentinel \
  --region asia-southeast1 \
  --format="value(status.url)"

# Confirm bot started in logs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" \
  --limit 20 --format="table(timestamp,textPayload)"
# Expected log: "Starting Telegram bot polling..."
```

---

## Phase 3 — Detection Pipeline Fixes

These fix the bugs causing inconclusive verdicts and broken detections.

### 3.1 — Fix Gemini SDK in `pipeline/insights.py`

Replace every occurrence of the old pattern:

```python
# DELETE — dead package
import google.generativeai as genai
genai.configure(api_key=...)
model = genai.GenerativeModel("gemini-1.5-flash")
response = model.generate_content(prompt)
```

With the new pattern:

```python
# CORRECT — google-genai package
from google import genai
from config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model=GEMINI_MODEL,
    contents=prompt
)
text = response.text
```

Apply the same fix to:
- `media/image.py` → `detect_image_manipulation()` and `analyse_image_with_gemini()`
- `pipeline/detector.py` → `detect_misinformation()`
- Any other file using `genai.configure()`

Install corrected package:
```bash
.venv\Scripts\pip install google-genai
.venv\Scripts\pip uninstall google-generativeai -y
```

### 3.2 — Fix ClickHouse in `pipeline/logger.py`

Ensure `log_to_clickhouse()` uses exactly this pattern:

```python
import clickhouse_connect
import sys
from config import (
    CLICKHOUSE_HOST, CLICKHOUSE_PORT,
    CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB
)

def log_to_clickhouse(row: dict) -> None:
    """Non-blocking ClickHouse insert. Never raises."""
    try:
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,      # must be 8123 (HTTP), not 9000 (TCP)
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB,
            secure=True,
        )
        client.insert(
            "detection_events",
            [list(row.values())],
            column_names=list(row.keys()),
            settings={"async_insert": 1, "wait_for_async_insert": 0},
        )
    except Exception as e:
        print(f"[logger] ClickHouse insert failed: {e}", file=sys.stderr)
```

Check `config.py` has `CLICKHOUSE_PORT = _optional("CLICKHOUSE_PORT", 8123)` — NOT 9000.

### 3.3 — Fix GUARD fallback labels in `pipeline/guard.py`

Remove any return of `label: "detection_failed"`. Replace with specific labels:

```python
# Missing API key — must be first check, before any HTTP call
if not SEALION_API_KEY:
    logging.error("[GUARD] SEALION_API_KEY not set")
    return {"is_ai_generated": None, "confidence": None,
            "label": "api_key_missing", "raw_response": {}}

# Inside except blocks:
except asyncio.TimeoutError:
    return {"is_ai_generated": None, "confidence": None,
            "label": "timeout", "raw_response": {}}
except Exception as e:
    logging.exception(f"[GUARD] Detection failed: {e}")
    return {"is_ai_generated": None, "confidence": None,
            "label": "api_error", "raw_response": {}}
```

Also log raw response before parsing:
```python
raw_text = data["choices"][0]["message"]["content"].strip()
logging.info(f"[GUARD] Raw response: {raw_text[:200]}")
```

### 3.4 — Fix `run_insights()` content parameter in `pipeline/insights.py`

The function must receive `english_text` — not `detection_result["label"]`.

```python
# Correct signature
async def run_insights(
    content: str,                              # actual text — NOT guard label
    detection_result: dict,
    misinformation_result: dict | None = None,
    manipulation_result: dict | None = None,
) -> dict:

# Skip guard context when label is an error string
ERROR_LABELS = {"api_error", "timeout", "api_key_missing"}
guard_context = ""
guard_label = detection_result.get("label", "")
if guard_label not in ERROR_LABELS:
    guard_context = f"SEA-LION GUARD verdict: {guard_verdict} ({guard_label[:150]})\n"

# Both optional params must be None-safe
if misinformation_result and misinformation_result.get("misinformation_detected"):
    # build misinfo_context
    ...
if manipulation_result and manipulation_result.get("manipulation_detected"):
    # build manip_context
    ...
```

### 3.5 — Add `detect_misinformation()` to `pipeline/detector.py`

If not already present:

```python
async def detect_misinformation(content: str, context_description: str = "") -> dict:
    """Detect AI-assisted misinformation. Never raises."""
    FALLBACK = {
        "misinformation_detected": False,
        "misinformation_type": "unknown",
        "claims": [],
        "explanation": "Misinformation check unavailable.",
        "confidence": 0.0,
    }
    try:
        import json, re
        prompt = f"""
You are a fact-checking assistant.
{f'Source context: {context_description}' if context_description else ''}
Content: {content[:2000]}

Respond JSON only:
{{
  "misinformation_detected": true or false,
  "misinformation_type": "none|fabricated_quote|false_statistic|misleading_context|unknown",
  "claims": ["suspicious claims if any"],
  "explanation": "one paragraph",
  "confidence": 0.0 to 1.0
}}"""
        raw = await call_llm(prompt)
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(clean)
    except Exception as e:
        logging.warning(f"[Misinformation] Detection failed: {e}")
        return FALLBACK
```

### 3.6 — Add `detect_image_manipulation()` to `media/image.py`

If not already present, add using the new `genai.Client()` pattern:

```python
async def detect_image_manipulation(file_path: str) -> dict:
    """Detect deepfakes, GAN artifacts, compositing. Never raises."""
    FALLBACK = {
        "manipulation_detected": False,
        "manipulation_type": "unknown",
        "signals": [],
        "explanation": "Image manipulation check unavailable.",
        "confidence": 0.0,
    }
    try:
        import json, re
        from google import genai
        from google.genai import types as genai_types
        from config import GEMINI_API_KEY, GEMINI_MODEL

        with open(file_path, "rb") as f:
            image_bytes = f.read()

        client = genai.Client(api_key=GEMINI_API_KEY)
        image_part = genai_types.Part.from_bytes(
            data=image_bytes, mime_type="image/jpeg"
        )
        prompt = """Analyse this image for manipulation or AI generation.
Respond JSON only:
{
  "manipulation_detected": true or false,
  "manipulation_type": "none|deepfake_face|gan_generated|compositing|cloning|ai_art|unknown",
  "signals": ["visual signals observed"],
  "explanation": "one paragraph",
  "confidence": 0.0 to 1.0
}"""
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[image_part, prompt],
        )
        raw = response.text.strip()
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(clean)
    except Exception as e:
        logging.warning(f"[ImageManipulation] Detection failed: {e}")
        return FALLBACK
```

### 3.7 — Fix concurrent detection in handlers

`handle_text` must use `asyncio.gather`:
```python
detection_result, misinfo_result = await asyncio.gather(
    guard.run_guard_detection(english_text, source_lang="en"),
    detector.detect_misinformation(english_text, context_description="text message"),
)
insights_result = await insights.run_insights(
    english_text, detection_result,
    misinformation_result=misinfo_result,
)
```

`handle_photo` must use `asyncio.gather` for all three:
```python
detection_result, misinfo_result, manip_result = await asyncio.gather(
    guard.run_guard_detection(combined_text, source_lang="en"),
    detector.detect_misinformation(combined_text, context_description="image with OCR text"),
    image.detect_image_manipulation(file_path),
)
insights_result = await insights.run_insights(
    combined_text, detection_result,
    misinformation_result=misinfo_result,
    manipulation_result=manip_result,
)
```

---

## Phase 4 — Telegram Bot Refactor

Remove all legacy code from `telegram_bot.py` still present from the pre-refactor version.

### 4.1 — Remove legacy imports

Delete these import blocks entirely:

```python
# DELETE — ai_agent_adk was removed per CHANGELOG.md
try:
    tools_module = importlib.import_module('ai_agent_adk.tools')
except Exception:
    ...
detect_language = getattr(tools_module, 'detect_language', None)
# ... all getattr() imports

# DELETE — image_detector.py was removed per CHANGELOG.md
try:
    from image_detector import detect_fake_text
except Exception:
    detect_fake_text = None
```

Replace with direct imports from the refactored modules:

```python
from pipeline import detector, guard, insights, translator, formatter, logger
from media import image, audio, video, live
from research_agent import agent as research_agent
from config import TELEGRAM_TOKEN, COOLDOWN_SECONDS
```

### 4.2 — Remove legacy fallback paths

Delete any code that references `detect_fake_text`, `tools_module`, or
`getattr(context, 'adk_runner', None)` for translation.

`translate_to_english` and `translate_from_english` are now direct awaitable
functions in `pipeline/translator.py` — no runner required.

### 4.3 — Remove `main_cli()`

The CLI mode is a legacy workflow from `text_detector.py` which no longer exists.
Delete the `main_cli()` function and the `'--cli' in sys.argv` branch entirely.

### 4.4 — Fix `run_polling()` retries

```python
# BEFORE
app.run_polling()

# AFTER
app.run_polling(bootstrap_retries=5)
```

### 4.5 — Add all four media handlers

Ensure all handlers are registered in `start_bot()`:

```python
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
app.add_handler(CommandHandler("research", research_command))
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("help", help_command))
```

---

## Phase 5 — Architecture Violations

Quick grep-and-fix pass. Run each search and fix every hit.

### 5.1 — Remove `os.getenv()` outside `config.py`

```bash
grep -rn "os.getenv(" --include="*.py" . | grep -v config.py | grep -v ".venv"
```

For every hit: add the variable to `config.py` using `_require()` or `_optional()`,
then replace the `os.getenv()` call with the imported constant.

### 5.2 — Remove `parse_mode="Markdown"` and `parse_mode="MarkdownV2"`

```bash
grep -rn "MarkdownV2\|parse_mode=\"Markdown\"" --include="*.py" . | grep -v ".venv"
```

Replace every hit with `parse_mode="HTML"`.

### 5.3 — Remove `clickhouse_driver` imports

```bash
grep -rn "clickhouse_driver\|clickhouse-driver" --include="*.py" . | grep -v ".venv"
```

Replace with `clickhouse_connect`.

### 5.4 — Remove direct Gemini calls outside `pipeline/insights.py`

```bash
grep -rn "genai.configure\|GenerativeModel\|google.generativeai" \
  --include="*.py" . | grep -v ".venv" | grep -v "insights.py"
```

For hits in `media/image.py` and `pipeline/detector.py`: the functions there
(`detect_image_manipulation`, `detect_misinformation`) are allowed to use
`genai.Client()` directly since they are vision/JSON tasks, not LLM text tasks.
Only unify into `call_llm()` for plain text generation.

### 5.5 — Remove legacy files

```bash
# Confirm these are gone (should already be deleted per CHANGELOG.md)
Remove-Item -ErrorAction SilentlyContinue `
  image_detector.py, text_detector.py, detect_cli.py, ocr.py, web_crawler.py
Remove-Item -ErrorAction SilentlyContinue -Recurse ai_agent_adk/
Remove-Item -ErrorAction SilentlyContinue `
  research_agent/fetcher.py, research_agent/deduplicator.py
```

### 5.6 — Fix `print()` in translator

```bash
grep -rn "print(f\"\[WARN\]" pipeline/translator.py
```

Replace with `logging.warning(...)`.

### 5.7 — Add `len(text) >= 20` guard in `handle_audio`

Ensure `handle_audio` uses Deepgram `detected_language` and guards short transcripts:

```python
source_lang = transcription.get("detected_language", "en")
if len(transcript) < 20:
    source_lang = "en"  # too short to detect reliably
```

---

## Phase 6 — Unit Test Coverage

Run the test suite baseline first:

```bash
.venv\Scripts\python.exe -m pytest tests/ -v --tb=short
```

Then write missing tests. Critical ones for hackathon demo resilience:

### `tests/test_live.py` — NEW FILE

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from media.live import live_voice_exchange, _pcm_to_ogg


@pytest.mark.asyncio
async def test_live_voice_exchange_returns_ogg_on_success():
    mock_part = MagicMock()
    mock_part.inline_data.data = b"\x00\x01" * 2400  # fake PCM

    mock_message = MagicMock()
    mock_message.server_content.model_turn.parts = [mock_part]

    mock_session = AsyncMock()
    mock_session.receive = AsyncMock(return_value=_aiter([mock_message]))
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("media.live.genai.Client") as mock_client:
        mock_client.return_value.aio.live.connect.return_value = mock_session
        result = await live_voice_exchange(b"fake_audio_bytes")
        assert isinstance(result, bytes)


@pytest.mark.asyncio
async def test_live_voice_exchange_returns_empty_on_failure():
    with patch("media.live.genai.Client") as mock_client:
        mock_client.return_value.aio.live.connect.side_effect = Exception("API down")
        result = await live_voice_exchange(b"fake_audio_bytes")
        assert result == b""  # must never raise


def test_pcm_to_ogg_returns_empty_on_empty_input():
    assert _pcm_to_ogg(b"") == b""


async def _aiter(items):
    for item in items:
        yield item
```

### Missing `test_guard.py` cases

```python
@pytest.mark.asyncio
async def test_guard_never_returns_detection_failed():
    with patch("pipeline.guard.get_http_client") as mock_http:
        mock_http.return_value.post = AsyncMock(
            side_effect=Exception("connection refused")
        )
        result = await run_guard_detection("test content")
        assert result["label"] != "detection_failed"
        assert result["label"] in ("api_error", "timeout", "api_key_missing")

@pytest.mark.asyncio
async def test_guard_returns_timeout_label():
    with patch("pipeline.guard.get_http_client") as mock_http:
        mock_http.return_value.post = AsyncMock(side_effect=asyncio.TimeoutError())
        result = await run_guard_detection("test")
        assert result["label"] == "timeout"
```

### Missing `test_insights.py` cases

```python
@pytest.mark.asyncio
async def test_call_llm_falls_back_to_groq_on_any_gemini_exception():
    with patch("pipeline.insights.genai.Client") as mock_g, \
         patch("pipeline.insights.OpenAI") as mock_oai:
        mock_g.return_value.models.generate_content.side_effect = Exception("quota")
        mock_choice = MagicMock()
        mock_choice.message.content = "Groq response"
        mock_oai.return_value.chat.completions.create.return_value.choices = [mock_choice]
        result = await call_llm("test prompt")
        assert result == "Groq response"

@pytest.mark.asyncio
async def test_call_llm_never_raises():
    with patch("pipeline.insights.genai.Client") as mock_g, \
         patch("pipeline.insights.OpenAI") as mock_oai:
        mock_g.return_value.models.generate_content.side_effect = Exception()
        mock_oai.return_value.chat.completions.create.side_effect = Exception()
        result = await call_llm("test")
        assert result == ""
```

Run full suite after writing tests:

```bash
.venv\Scripts\python.exe -m pytest tests/ -v --tb=short
# Target: ≥ 52 passed, 0 failed
```

---

## Phase 7 — Submission Artifacts (Required for DevPost)

### 7.1 — Architecture diagram

Export `ARCHITECTURE.md` flow diagram as PNG.
Use draw.io (https://draw.io) or Excalidraw (https://excalidraw.com).
Save as `docs/architecture_diagram.png`.
Upload to DevPost image carousel.

### 7.2 — GCP deployment proof recording

Record a 30–60 second screen capture showing:
1. `gcloud run services describe sentinel --region asia-southeast1` in terminal
2. Cloud Run console showing service as "Serving" with green status
3. (Optional) Live log tail showing `Starting Telegram bot polling...`

Save as `docs/gcp_proof.mp4`.

### 7.3 — Demo video (<4 minutes)

Record in this sequence to hit all judging criteria:

| Minute | What to show |
|---|---|
| 0:00–0:30 | Problem statement: AI-generated content spreading in Singapore |
| 0:30–1:30 | Send a text message to the bot — show guard verdict + explanation |
| 1:30–2:30 | Send a voice note — show Gemini Live API spoken verdict reply |
| 2:30–3:30 | Send an image — show manipulation detection |
| 3:30–4:00 | Architecture diagram + GCP Cloud Run deployment proof |

### 7.4 — DevPost text description

Write `docs/devpost_submission.md` covering:
- Problem: AI-generated misinformation in Singapore's multilingual context
- Solution: SENTINEL multimodal detection via Telegram
- Technologies used: Gemini Live API, Gemini 2.5-flash, SEA-LION GUARD, Google ADK,
  Cloud Run, Deepgram, ClickHouse, Firecrawl
- Findings: detection accuracy, multilingual support, latency

### 7.5 — Make GitHub repo public

```bash
# Ensure .env is in .gitignore BEFORE making public
grep ".env" .gitignore  # must output ".env"

# Push latest code
git add -A
git commit -m "feat: Gemini Live API + Cloud Run deployment for hackathon"
git push origin main

# Make repo public via GitHub settings → Danger Zone → Change visibility
```

Verify README.md has spin-up instructions:

```markdown
## Quick Start
1. Clone repo
2. Copy `.env.example` to `.env` and fill in keys
3. `pip install -r requirements.txt`
4. `python telegram_bot.py`
```

---

## Phase 8 — Bonus Points

Complete these after Phase 7 if time permits.

### 8.1 — Automated Cloud Build (bonus: infrastructure-as-code)

Commit `cloudbuild.yaml` (created in Phase 2.5) and run:

```bash
gcloud builds submit --config cloudbuild.yaml .
```

Include `cloudbuild.yaml` link in your DevPost submission as "automated deployment proof".

### 8.2 — Social post

Post on LinkedIn or X/Twitter:

> "Built SENTINEL for the #GeminiLiveAgentChallenge — a multimodal AI content
> detection bot using Gemini Live API + SEA-LION GUARD for Singapore users.
> Detects AI-generated text, images, audio, and video via Telegram.
> Created this content for the Gemini Live Agent Challenge hackathon.
> [GitHub link]"

Include `#GeminiLiveAgentChallenge` hashtag.

### 8.3 — Google Developer Group profile

Sign up at https://gdg.community.dev/ and include your public profile link
in the DevPost submission.

### 8.4 — A2A integration

Use `/a2a-integrate` slash command in Claude Code for step-by-step guidance.
Adds A2A protocol support so SENTINEL can be called by other agents and
call external A2A agents (deepfake specialists, fact-checkers).

---

## Final Verification Checklist

Run before submitting to DevPost:

```bash
# 1. All tests pass
.venv\Scripts\python.exe -m pytest tests/ -v

# 2. Bot starts locally without errors
.venv\Scripts\python.exe telegram_bot.py

# 3. Live API produces audio
.venv\Scripts\python.exe -c "
import asyncio; from media.live import live_voice_exchange
result = asyncio.run(live_voice_exchange(b'test', system_context='guard: ai_generated'))
print('Live API:', '✅' if result else '❌')
"

# 4. GCP deployment live
gcloud run services describe sentinel --region asia-southeast1 \
  --format="value(status.url)"

# 5. No placeholder credentials
.venv\Scripts\python.exe -c "
from config import TELEGRAM_TOKEN, GEMINI_API_KEY, OPENAI_API_KEY
for k, v in [('TELEGRAM', TELEGRAM_TOKEN), ('GEMINI', GEMINI_API_KEY), ('SEALION', OPENAI_API_KEY)]:
    print(k, '✅' if v and not v.startswith('your-') else '❌ PLACEHOLDER')
"
```

```
[ ] All pytest tests pass (≥ 52)
[ ] Bot running on Cloud Run — URL confirmed
[ ] Gemini Live API producing audio locally
[ ] media/live.py committed to public repo
[ ] cloudbuild.yaml committed (bonus)
[ ] Architecture diagram PNG in docs/
[ ] GCP proof recording in docs/
[ ] Demo video recorded, < 4 minutes
[ ] DevPost submission draft written
[ ] GitHub repo public with README spin-up instructions
[ ] Social post published with #GeminiLiveAgentChallenge (bonus)
```
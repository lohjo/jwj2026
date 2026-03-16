# SENTINEL — Technical Implementation Details

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Runtime** | Python 3.11+ | Async-first backend with `asyncio` |
| **Bot Framework** | python-telegram-bot ≥21.0 | Telegram handlers, polling mode |
| **Web Framework** | FastAPI + Uvicorn | REST, SSE streaming, WebSocket endpoints |
| **Primary LLM** | Google Gemini 2.5 Flash | Detection insights, topic extraction, rumour prediction, counter-narrative generation |
| **Live Audio LLM** | Gemini 2.5 Flash Native Audio | Bidirectional audio via WebSocket (STT + TTS in one session) |
| **Fallback LLM** | Groq / Llama 3.3 70B | Automatic fallback on any Gemini exception |
| **Safety Guard** | SEA-LION GUARD (AI Singapore) | AI-generation detection + safety classification |
| **Translation** | SEA-LION Gemma 27B-IT | Bidirectional EN↔ZH/MS/TA/Singlish translation |
| **Embeddings** | Gemini `embedding-001` | 768-dimensional text vectors for RAG |
| **Vector DB / RAG** | ClickHouse (MergeTree + cosineDistance) | Hybrid topic + vector search over historical articles |
| **Telemetry DB** | ClickHouse (SummingMergeTree) | Detection event logging with hourly pre-aggregation |
| **Speech-to-Text** | Deepgram Nova-2 | Audio transcription with language detection |
| **Text-to-Speech** | ElevenLabs (fallback) | Multilingual TTS when Live API is unavailable |
| **Image Analysis** | Gemini Vision + OpenCV + Tesseract | OCR, AI-signal detection, manipulation heuristics |
| **Video Analysis** | OpenCV + pydub + ffmpeg | Frame extraction, audio separation |
| **Web Scraping** | Firecrawl | Live source retrieval (POFMA, CNA, MOH) + research |
| **HTTP Client** | httpx (async) | Connection-pooled API calls |
| **Messaging** | Telegram Bot API | Detection replies + counter-narrative deployment |
| **Config** | python-dotenv | Single-file env-var access (`config.py`) |
| **Hosting** | Google Cloud Run (asia-southeast1) | Managed container deployment |
| **CI/CD** | Cloud Build | Automated Docker build → push → deploy |
| **Testing** | pytest + pytest-asyncio | Async unit tests with full API mocking |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        ENTRY POINTS                                      │
│                                                                          │
│  telegram_bot.py (polling)         app.py (FastAPI)                      │
│  ├─ /start, /help                  ├─ GET  /                (dashboard)  │
│  ├─ /detect <text>                 ├─ POST /analyse-stream  (SSE)        │
│  ├─ /research <query>              ├─ POST /analyse-image-stream (SSE)   │
│  ├─ /predict <announcement>  NEW   ├─ POST /analyse-audio   (Live API)  │
│  ├─ handle_text                    ├─ WS   /ws/live-audio   (WebSocket)  │
│  ├─ handle_photo                   ├─ POST /predict-stream  (SSE)  NEW   │
│  ├─ handle_audio                   └─ POST /deploy-telegram        NEW   │
│  └─ handle_video                                                         │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
┌──────────────────────┐  ┌──────────────────────────────────────────────┐
│   REACTIVE PIPELINE  │  │         PROACTIVE PIPELINE  (NEW)            │
│   (Detect & Explain) │  │         (Predict & Counter)                  │
│                      │  │                                              │
│  pipeline/guard.py   │  │  pipeline/predictor.py                       │
│   → SEA-LION GUARD   │  │   ├─ extract_topics()                       │
│                      │  │   │   → topics, communities, triggers,       │
│  pipeline/detector.py│  │   │     search queries (Gemini structured)   │
│   → misinfo detect   │  │   │                                         │
│   → image manip.     │  │   ├─ retrieve_sources() (parallel)          │
│                      │  │   │   ├─ Firecrawl → POFMA, CNA, MOH        │
│  pipeline/insights.py│  │   │   └─ ClickHouse RAG → historical vectors│
│   → LLM explanation  │  │   │                                         │
│   → Gemini→Groq      │  │   └─ predict_rumours()                      │
│     fallback         │  │       → 3-8 predictions with risk scores    │
│                      │  │       → counter-narratives in EN/ZH/MS/TA   │
│  media/image.py      │  │       → historical pattern matches          │
│   → OCR + OpenCV     │  │       → policy recommendations             │
│                      │  │                                              │
│  media/audio.py      │  │  pipeline/embeddings.py                      │
│   → Deepgram STT     │  │   → Gemini embedding-001 (768-dim)          │
│   → ElevenLabs TTS   │  │   → ClickHouse article_embeddings table     │
│                      │  │                                              │
│  media/live.py       │  │  pipeline/deployer.py                        │
│   → Gemini Live API  │  │   → Telegram counter-narrative push         │
│   → bidirectional    │  │   → message chunking (4000 char)            │
│     audio WebSocket  │  │   → member count reporting                  │
│                      │  │                                              │
│  media/video.py      │  │  pipeline/rag.py                             │
│   → frame extraction │  │   → hybrid search (topic + vector)          │
│   → audio separation │  │   → credibility-weighted scoring            │
└──────────────────────┘  └──────────────────────────────────────────────┘
          │                             │
          └──────────────┬──────────────┘
                         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     SHARED INFRASTRUCTURE                                │
│                                                                          │
│  config.py          → single env-var access point                        │
│  pipeline/translator.py → SEA-LION Gemma 27B-IT (EN↔ZH/MS/TA)           │
│  pipeline/formatter.py  → HTML formatting (parse_mode="HTML" only)       │
│  pipeline/logger.py     → ClickHouse non-blocking telemetry              │
│  research_agent/        → Firecrawl search → LLM summarise → cache       │
│  static/index.html      → SPA web dashboard                             │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## How It Works: Reactive Path (Detect & Explain)

### Text Detection Flow

```
User sends text message
  → detect_language(text) → ISO 639-1 code
  → if lang ≠ "en": translate_to_english(text, lang) via SEA-LION Gemma
  → [GUARD + misinformation detection] run concurrently via asyncio.gather
      ├─ run_guard_detection(english_text) → SEA-LION GUARD API
      └─ detect_misinformation(english_text) → Gemini-powered LLM analysis
  → run_insights(guard_result, misinfo_result) → plain-language explanation
  → if lang ≠ "en": translate_from_english(explanation, lang)
  → format_detection_message() → HTML reply
  → send to user
  → [background] auto-research if flagged + ClickHouse log
```

### Image Detection Flow

```
User sends photo
  → download image
  → analyse_image_with_gemini() → description + OCR + AI signals
  → detect_language(ocr_text) → translate if non-EN
  → run_full_detection(text, image_path)
      ├─ GUARD + misinformation (asyncio.gather)
      └─ detect_image_manipulation() → OpenCV heuristics
           ├─ Laplacian variance (smoothness)
           └─ Canny edge density
  → run_insights() → translate back → format → reply
  → [background] auto-research + ClickHouse log → delete temp file
```

### Audio Detection Flow

```
User sends voice note
  → download audio file
  → Deepgram STT → transcript + detected_language
  → translate to English if needed
  → run_full_detection(english_text)
  → Gemini Live API → inject detection context → spoken verdict (OGG)
  → if Live API fails: ElevenLabs TTS fallback
  → send voice note reply + text fallback
  → [background] auto-research + ClickHouse log → cleanup temp files
```

### Video Detection Flow

```
User sends video
  → download video file
  → OpenCV frame extraction (max 5 frames at regular intervals)
  → each frame → Gemini Vision analysis
  → pydub audio extraction → Deepgram STT
  → combine visual + audio analysis
  → translate if needed → run_full_detection() → insights
  → format → reply → cleanup
```

---

## How It Works: Proactive Path (Predict & Counter) — NEW

### Rumour Prediction Flow

```
Comms officer submits announcement (Telegram /predict or web dashboard)
  │
  ▼
Step 1: Topic Extraction (Gemini 2.5 Flash, structured JSON output)
  → topics, affected communities, emotional triggers, search queries
  → streamed to web UI as SSE "step" event
  │
  ▼
Step 2: Source Retrieval (parallel)
  ├─ Path A: Firecrawl live search
  │   → pofmaoffice.gov.sg, channelnewsasia.com, moh.gov.sg
  │   → up to 15 sources with URL, title, content
  │   → each source streamed as SSE "source" event
  │
  └─ Path B: ClickHouse Hybrid RAG
      → embed announcement via Gemini embedding-001 (768-dim)
      → Phase 1: topic-filtered articles ranked by cosineDistance
      → Phase 2: pure vector search for remaining slots
      → deduplicate by URL, merge (topic-matched first)
      → filter threshold: cosineDistance ≤ 0.5
  │
  ▼
Step 3: Analyse & Predict (Gemini 2.5 Flash, structured output)
  → cross-reference RAG + live sources + extracted topics
  → generate 3-8 rumour predictions ranked by risk score:
      ├─ risk level (CRITICAL / HIGH / MEDIUM / LOW)
      ├─ risk score (0-100)
      ├─ predicted false narrative
      ├─ likely spread channel (WhatsApp, Twitter, Telegram, etc.)
      ├─ emotional trigger + demographic risk
      ├─ historical pattern match with similarity score
      ├─ time-to-spread estimate
      ├─ counter-narratives in EN, ZH, MS, TA
      ├─ supporting sources with URLs
      └─ policy recommendations
  → streamed as SSE "result" event
  │
  ▼
Step 4: Deployment (optional)
  → POST /deploy-telegram → send counter-narratives to community channels
  → messages chunked at 4000 characters (Telegram limit)
  → getChatMemberCount → report reach
  → confirmation with member count
```

---

## Hybrid RAG Implementation

Two-phase search combining topic relevance with vector similarity:

**Phase 1 — Topic-Filtered Search:**
```sql
SELECT id, url, title, content, credibility_score,
       cosineDistance(embedding, {query_vector}) AS distance
FROM article_embeddings
WHERE hasAny(topics, {extracted_topics})
  AND cosineDistance(embedding, {query_vector}) <= 0.5
ORDER BY distance ASC
LIMIT 10
```

**Phase 2 — Pure Vector Search:**
```sql
SELECT id, url, title, content, credibility_score,
       cosineDistance(embedding, {query_vector}) AS distance
FROM article_embeddings
WHERE id NOT IN ({phase1_ids})
  AND cosineDistance(embedding, {query_vector}) <= 0.5
ORDER BY distance ASC
LIMIT 5
```

Results are deduplicated by URL, merged (topic-matched articles prioritised), and tagged with credibility scores.

**Credibility Scoring:**

| Score | Source Type | Examples |
|-------|-----------|----------|
| 0.95 | Government | MOH, Gov.sg, POFMA Office |
| 0.90 | Established media | CNA, Straits Times, TODAY |
| 0.70 | Forums | HardwareZone, Reddit |
| 0.50 | Community/unverified | Blogs, social media |

The LLM is instructed to prioritise high-credibility sources for counter-narratives and use low-credibility sources to understand actual rumour language patterns.

---

## ClickHouse Schema

### Detection Events (existing)

```sql
CREATE TABLE detection_events (
  event_id      UUID DEFAULT generateUUIDv4(),
  timestamp     DateTime DEFAULT now(),
  user_id       String,          -- SHA-256 hashed for privacy
  content_type  Enum8('text'=1, 'image'=2, 'audio'=3, 'video'=4),
  guard_verdict Enum8('safe'=1, 'unsafe'=2, 'error'=3),
  misinfo       Bool DEFAULT false,
  manipulation  Bool DEFAULT false,
  explanation   String,
  model_versions Map(String, String),
  processing_ms UInt32
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (timestamp, event_id)
TTL timestamp + INTERVAL 90 DAY
```

### Article Embeddings (new — from ContextGuard)

```sql
CREATE TABLE article_embeddings (
  id               UUID DEFAULT generateUUIDv4(),
  url              String,
  title            String,
  content          String,
  domain           String,
  scraped_at       DateTime DEFAULT now(),
  topics           Array(String),
  credibility_score Float32 DEFAULT 0.5,
  embedding        Array(Float32)    -- 768-dim Gemini vectors
) ENGINE = MergeTree()
ORDER BY scraped_at
```

### Prediction Events (new)

```sql
CREATE TABLE prediction_events (
  event_id         UUID DEFAULT generateUUIDv4(),
  timestamp        DateTime DEFAULT now(),
  user_id          String,
  announcement     String,
  topics           Array(String),
  num_predictions  UInt8,
  max_risk_score   UInt8,
  rag_sources_used UInt8,
  live_sources_used UInt8,
  processing_ms    UInt32
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (timestamp, event_id)
TTL timestamp + INTERVAL 90 DAY
```

---

## LLM Call Patterns

### Standard Detection Path (insights.py::call_llm)

```
User request → call_llm(prompt)
  ├─ Try: Gemini 2.5 Flash (google-genai SDK)
  │   → on success: model_versions["llm_used"] = "gemini"
  └─ Catch ANY exception:
      ├─ Try: Groq / Llama 3.3 70B (openai SDK, base_url=groq)
      │   → on success: model_versions["llm_used"] = "groq"
      └─ Catch: return "" → model_versions["llm_used"] = "failed"
```

### Live Audio Path (media/live.py)

```
Audio input → Gemini Live API
  → WebSocket: client.aio.live.connect(model, config)
  → send audio chunks + detection context as system instruction
  → receive PCM16 audio stream
  → convert PCM → OGG (ffmpeg, pydub fallback)
  → return OGG bytes for Telegram voice note
  → on failure: return b"" (caller falls back to text reply)
```

### Prediction Path (pipeline/predictor.py) — NEW

```
Announcement → extract_topics(text) via Gemini (structured JSON)
  → retrieve_sources(topics, embedding) via Firecrawl + ClickHouse
  → predict_rumours(announcement, topics, sources) via Gemini (structured JSON)
  → all calls use Gemini→Groq fallback via call_llm()
```

---

## Gemini Live API Integration

SENTINEL uses the Gemini Live API (`gemini-2.5-flash-native-audio-latest`) for real-time bidirectional audio — the user sends a voice note and receives a spoken verdict.

**Protocol:**

```python
async with client.aio.live.connect(model=GEMINI_LIVE_MODEL, config=config) as session:
    # 1. Send audio + detection context
    await session.send(input=LiveClientRealtimeInput(
        media_chunks=[Blob(data=audio_bytes, mime_type="audio/ogg")]
    ))
    await session.send(input=".", end_of_turn=True)

    # 2. Receive streamed PCM16 audio
    pcm_audio = b""
    async for message in session.receive():
        if message.server_content and message.server_content.model_turn:
            for part in message.server_content.model_turn.parts:
                if part.inline_data:
                    pcm_audio += part.inline_data.data

    # 3. Convert PCM → OGG for Telegram
    return pcm_to_ogg(pcm_audio)
```

**System instruction injection:** Detection context (GUARD verdict, misinfo result) is injected into the Live API session as a system instruction, so the spoken verdict is informed by the full detection pipeline — not just the raw audio.

---

## Translation Engine

All translation goes through `pipeline/translator.py` using **SEA-LION Gemma 27B-IT**:

| Direction | Behaviour |
|-----------|-----------|
| Pre-detection (non-EN → EN) | Preserve exact phrasing — do NOT fix grammar |
| Post-detection (EN → user lang) | Translate naturally and fluently |
| Counter-narratives (EN → ZH/MS/TA) | Single-call multilingual generation for consistency |
| Audio language detection | Use Deepgram `detected_language`, NOT langdetect |

**Always kept in English:** `AI-generated`, `deepfake`, `GUARD`, `OCR`, `confidence score`

**Supported languages:** EN, ZH, MS, TA, ID, TH, VI, TL, Singlish

---

## Key Technical Decisions

1. **Gemini 2.5 Flash for all LLM tasks** — Structured JSON output with schema enforcement, fast inference for real-time SSE streaming, and the hackathon's mandatory Gemini requirement.

2. **ClickHouse for both telemetry and vector search** — Native `cosineDistance()` on `Array(Float32)` with MergeTree engine. Avoids a separate vector DB while supporting hybrid topic + vector queries and time-series telemetry in a single database.

3. **Hybrid RAG (topic + vector)** — Pure vector search misses Singapore-specific context. Two-phase approach (topic-filtered first, pure cosine fill) improves precision for localised misinformation patterns.

4. **Single-call multilingual generation** — All 4 language counter-narratives generated in one LLM call to maintain translation consistency across English, Mandarin, Bahasa Melayu, and Tamil.

5. **Credibility-weighted sources** — RAG sources carry credibility scores (0.95 govt → 0.50 community) so the LLM prioritises authoritative sources for counter-narratives while using forum posts to understand actual rumour language.

6. **SSE over WebSockets for pipeline progress** — Server-Sent Events provide simpler unidirectional streaming for step-by-step processing updates in the web dashboard.

7. **Reactive + proactive in one platform** — Instead of two separate tools, SENTINEL handles both use cases (detect existing content and predict emerging misinformation) through a shared infrastructure of Gemini, ClickHouse, Firecrawl, and Telegram.

8. **SEA-LION for Singapore context** — AI Singapore's SEA-LION models (GUARD for safety, Gemma for translation) are trained on Southeast Asian languages and cultural context, outperforming generic models for Singlish, Mandarin, Malay, and Tamil.

9. **Gemini Live API for voice verdicts** — Replaces separate STT→LLM→TTS pipeline with a single bidirectional WebSocket session, reducing latency and satisfying the hackathon's Live Agents category requirement.

10. **Never-raise contract** — All detection functions return structured dicts on failure. No exceptions propagate to Telegram handlers. This makes the bot resilient to any single API outage.

---

## Environment Variables

```env
# Telegram
TELEGRAM_TOKEN=                        # Bot token from @BotFather

# Gemini / Google
GEMINI_API_KEY=                        # Google AI Studio or Vertex AI key
GEMINI_MODEL=gemini-2.5-flash          # Primary LLM
GEMINI_LIVE_MODEL=gemini-2.5-flash-native-audio-latest  # Live API model
GEMINI_LIVE_VOICE=Aoede                # Live API voice
GOOGLE_GENAI_USE_VERTEXAI=FALSE        # TRUE to route via Vertex AI
GOOGLE_CLOUD_PROJECT=                  # Required if Vertex AI
GOOGLE_CLOUD_LOCATION=asia-southeast1

# SEA-LION (guard + translation)
OPENAI_API_KEY=                        # SEA-LION API key
OPENAI_API_BASE=https://api.sea-lion.ai/v1
GUARD_MODEL=aisingapore/SEA-Guard
TRANSLATOR_MODEL=aisingapore/Gemma-SEA-LION-v4-27B-IT

# Groq (LLM fallback)
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# Speech
DEEPGRAM_API_KEY=                      # Deepgram Nova-2 STT
ELEVENLABS_API_KEY=                    # ElevenLabs TTS (fallback)
ELEVENLABS_VOICE_ID=

# ClickHouse
CLICKHOUSE_HOST=                       # ClickHouse Cloud host
CLICKHOUSE_PORT=8443
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
CLICKHOUSE_DB=agent_logs

# Research / Scraping
FIRECRAWL_API_KEY=                     # Firecrawl search + scrape

# Bot behaviour
COOLDOWN_SECONDS=3.0                   # Per-user rate limit
```

---

## Deployment

### Google Cloud Run

```bash
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY" \
  # ... (all other env vars)
```

### Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg libgl1-mesa-glx libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080
CMD ["python", "telegram_bot.py"]
```

### Automated CI/CD (Cloud Build)

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/sentinel', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/sentinel']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args: [run, deploy, sentinel, --image=gcr.io/$PROJECT_ID/sentinel,
           --region=asia-southeast1, --platform=managed,
           --allow-unauthenticated, --memory=2Gi, --cpu=2]
```

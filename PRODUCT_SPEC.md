# SENTINEL — Product Specification

## For: Development Team & Hackathon Judges

**Date:** 2026-03-16
**Status:** Hackathon build — Gemini Live Agent Challenge (deadline: Mar 16 2026)
**Category:** Live Agents — Gemini Live API

---

## 1. Overview

SENTINEL is a **full-spectrum information integrity platform** for Singapore. It operates in two modes:

1. **Reactive Detection** — Users send content (text, images, audio, video) and receive an AI-generated content verdict with confidence scores and explanations.
2. **Proactive Prediction** — Communications officers paste official announcements and receive a rumour forecast: predicted false narratives ranked by virality risk, with pre-written counter-narratives in 4 languages ready for deployment.

**Target users:** Singapore general public (reactive) and government/institutional comms officers (proactive).

**Languages:** English, Mandarin (中文), Bahasa Melayu, Tamil (தமிழ்), Singlish.

---

## 2. User Personas

### Persona A: General Public (Reactive Detection)

> **Ah Koh**, 58, receives a voice note on WhatsApp claiming that a new virus is spreading from dormitories. He forwards it to the SENTINEL Telegram bot. Within seconds, he gets a spoken verdict (in Mandarin) explaining that the claim contains fabricated statistics and no credible source supports it, plus a text breakdown with confidence scores.

**Needs:** Quick, multilingual, multimodal fact-checking accessible via Telegram.

### Persona B: Government Comms Officer (Proactive Prediction)

> **Sarah**, 32, is drafting a MOH advisory about a new disease cluster. Before publishing, she pastes the draft into SENTINEL's prediction dashboard. The system predicts 5 false narratives likely to emerge (rice shortage rumours, xenophobic targeting of migrant workers, folk remedy claims), ranked by risk. She deploys pre-written counter-narratives in 4 languages to 800+ community leaders via Telegram — hours before the misinformation can take hold.

**Needs:** Proactive rumour forecasting, multilingual counter-narratives, one-click community deployment.

---

## 3. Feature Inventory

### 3.1 Reactive Detection (Existing)

| Feature | Input | Output | Technology |
|---------|-------|--------|------------|
| **Text Detection** | Text message | AI-generation verdict + misinfo analysis + explanation | SEA-LION GUARD + Gemini |
| **Image Detection** | Photo | OCR + AI-signal detection + manipulation analysis | Gemini Vision + OpenCV |
| **Audio Detection** | Voice note | Transcription + detection + spoken verdict | Deepgram + Gemini Live API |
| **Video Detection** | Video clip | Frame analysis + audio transcription + combined verdict | OpenCV + Gemini Vision + Deepgram |
| **Auto-Research** | (triggered) | Web research enrichment when content is flagged | Firecrawl + LLM summarisation |
| **Translation** | (automatic) | Detect language → translate → detect → translate back | SEA-LION Gemma 27B-IT |

### 3.2 Proactive Prediction (New — from ContextGuard)

| Feature | Input | Output | Technology |
|---------|-------|--------|------------|
| **Topic Extraction** | Announcement text | Topics, communities, triggers, search queries | Gemini structured JSON |
| **Source Retrieval** | Extracted topics + embedding | Live sources + historical RAG matches | Firecrawl + ClickHouse RAG |
| **Rumour Prediction** | All context combined | 3-8 predictions with risk scores + counter-narratives | Gemini structured JSON |
| **Counter-Narratives** | Prediction results | Pre-written responses in EN/ZH/MS/TA | Single-call multilingual LLM |
| **Telegram Deployment** | Counter-narratives | Messages pushed to community leader channels | Telegram Bot API |
| **Demo Scenarios** | Button click | Pre-computed DORSCON Orange + Nipah scenarios | Cached data |

### 3.3 Web Dashboard

| Feature | Description |
|---------|-------------|
| **Text Analysis Tab** | Textarea → SSE streaming → step-by-step pipeline visualisation |
| **Image Analysis Tab** | Drag-and-drop upload → SSE streaming → Vision + GUARD + misinfo |
| **Audio Analysis Tab** | Microphone recording / file upload → Gemini Live API → spoken verdict |
| **Video Analysis Tab** | File upload → frame + audio analysis |
| **Research Tab** | Query input → Firecrawl web research → LLM summary |
| **Prediction Tab** (NEW) | Announcement input → SSE streaming → rumour forecast cards |
| **Counter-Narrative Display** (NEW) | 4-language toggle (EN/ZH/MS/TA) with copy + share buttons |
| **Action Panel** (NEW) | Deploy to Telegram button → confirmation modal → success toast |

### 3.4 Infrastructure

| Feature | Description |
|---------|-------------|
| **Gemini→Groq Fallback** | Automatic fallback on any Gemini exception, logged to ClickHouse |
| **ClickHouse Telemetry** | Non-blocking detection event logging with 90-day TTL |
| **ClickHouse RAG** | 768-dim vector search with topic filtering and credibility scoring |
| **Rate Limiting** | Per-user cooldown (configurable, default 3s) |
| **Cloud Run Hosting** | Managed container deployment on asia-southeast1 |
| **Health Checks** | `/health` endpoint for Cloud Run liveness probes |

---

## 4. User Flows

### 4.1 Reactive Detection (Telegram)

```
User sends content (text / photo / voice / video)
  │
  ├─ [Rate limit check] → if cooldown active: "Please wait X seconds"
  │
  ├─ [Language detection] → detect language of input
  │
  ├─ [Translation] → if non-EN: translate to English (preserve exact phrasing)
  │
  ├─ [Detection] → GUARD + misinformation + image manipulation (parallel)
  │
  ├─ [Insights] → LLM generates plain-language explanation
  │
  ├─ [Translation] → if non-EN: translate explanation back to user's language
  │
  ├─ [Format] → HTML verdict with confidence score + emoji indicators
  │   ✅ Human-Written | 🤖 AI-Generated | ❓ Unclear | 🚨 AI + Harmful
  │
  ├─ [Reply] → send HTML text + optional voice note (Gemini Live API)
  │
  └─ [Background]
      ├─ auto-research if flagged unsafe or misinformation
      └─ ClickHouse telemetry log (fire-and-forget)
```

### 4.2 Proactive Prediction (Telegram)

```
Comms officer sends: /predict <announcement text>
  │
  ├─ [Topic Extraction] → "Analysing announcement..."
  │   → extract topics, communities, triggers
  │
  ├─ [Source Retrieval] → "Searching for historical patterns..."
  │   ├─ Firecrawl → POFMA, CNA, MOH live sources
  │   └─ ClickHouse RAG → historical misinformation articles
  │
  ├─ [Prediction] → "Generating rumour forecast..."
  │   → 3-8 predictions with risk levels and counter-narratives
  │
  ├─ [Reply] → formatted prediction summary (HTML)
  │   🔴 CRITICAL (92) — "Sheng Siong out of rice"
  │   🟠 HIGH (87) — "Toilet paper shortage"
  │   🟡 MEDIUM (68) — "Government hiding cases"
  │
  └─ [Deploy option] → "Reply /deploy to push counter-narratives"
      → sends chunked multilingual messages to community channels
```

### 4.3 Proactive Prediction (Web Dashboard)

```
Step 1: INPUT
  ├─ Large text area: "Paste your announcement draft here..."
  ├─ "Load Demo" button → DORSCON Orange or Nipah scenario
  └─ "Analyse" button (primary CTA)

Step 2: PROCESSING (SSE real-time)
  ├─ "Extracting topics and communities..." ✓
  │   → extracted topics appear in collapsible dropdown
  ├─ "Retrieving authoritative sources..." ✓
  │   → each source appears as it's found (live streaming)
  └─ "Generating rumour predictions..." ✓

Step 3: RESULTS
  ├─ Summary bar: "5 predicted false narratives"
  ├─ Expandable rumour cards sorted by risk score descending:
  │   ├─ Risk badge (CRITICAL/HIGH/MEDIUM/LOW with colour)
  │   ├─ Predicted false narrative (title)
  │   ├─ Likely spread channel + time-to-spread
  │   ├─ Emotional trigger + demographic risk
  │   ├─ Historical pattern match with similarity score
  │   ├─ Counter-narratives (4-language toggle: EN/ZH/MS/TA)
  │   ├─ Supporting sources with URLs
  │   └─ Policy recommendations
  └─ Action panel at bottom

Step 4: DEPLOYMENT
  ├─ "Deploy to Community Leaders" button
  │   → confirmation modal: "Counter-narratives will be sent to N leaders in 4 languages"
  │   → on confirm: POST /deploy-telegram
  │   → success toast with member count
  ├─ Copy individual counter-narratives
  └─ Share via WhatsApp deep link
```

---

## 5. Data Structures

### 5.1 Detection Result (Reactive)

```python
{
    "is_safe": True | False | None,
    "guard": {
        "is_ai_generated": True | False | None,
        "confidence": 0.0-1.0 | None,
        "label": "safe" | "unsafe" | "api_error",
        "safety_flag": "safe" | "unsafe",
        "raw_response": {}
    },
    "misinformation": {
        "misinformation_detected": True | False,
        "misinformation_type": "fabricated_quote" | "false_statistic" | ...,
        "claims": [...],
        "explanation": "...",
        "confidence": 0.0-1.0
    },
    "manipulation": {                      # images/video only
        "manipulation_detected": True | False,
        "manipulation_type": "ai_generated" | "spliced" | ...,
        "signals": [...],
        "explanation": "...",
        "confidence": 0.0-1.0
    },
    "insights": "Plain-language explanation...",
    "model_versions": {
        "guard": "SEA-Guard",
        "llm_used": "gemini" | "groq" | "failed"
    }
}
```

### 5.2 Prediction Result (Proactive — NEW)

```python
{
    "announcement": "Original announcement text...",
    "topics": {
        "topics": ["DORSCON Orange", "COVID-19"],
        "communities": ["Mandarin-speaking elderly", "heartland residents"],
        "triggers": ["supply scarcity anxiety", "institutional distrust"],
        "search_queries": ["singapore rice shortage panic buying", ...]
    },
    "sources": {
        "live": [                          # from Firecrawl
            {"url": "...", "title": "...", "content": "...", "domain": "...",
             "credibility_score": 0.95}
        ],
        "rag": [                           # from ClickHouse
            {"url": "...", "title": "...", "content": "...", "domain": "...",
             "credibility_score": 0.90, "similarity": 0.82}
        ]
    },
    "historical_patterns": [
        {"event": "SARS 2003 panic buying", "similarity": 87,
         "source_url": "https://..."}
    ],
    "predictions": [
        {
            "id": "pred-001",
            "risk": "CRITICAL",
            "risk_score": 92,
            "title": "Sheng Siong and NTUC have run out of rice",
            "channel": "WhatsApp (Mandarin groups)",
            "trigger": "Survival anxiety — fear of food shortage",
            "demographic_risk": "Mandarin-speaking elderly, heartland residents",
            "historical_match": "Matches 2003 SARS panic-buying pattern",
            "time_to_spread": "~2-4 hours",
            "counter_narratives": {
                "en": "This is not true. Singapore's rice supply remains stable...",
                "zh": "这不是事实。新加坡的大米供应保持稳定...",
                "ms": "Ini tidak benar. Bekalan beras Singapura kekal stabil...",
                "ta": "இது உண்மையல்ல. சிங்கப்பூரின் அரிசி விநியோகம்..."
            },
            "sources": [
                {"title": "POFMA correction order", "url": "https://..."}
            ],
            "policy_recommendations": [
                "Issue joint statement with NTUC FairPrice within 1 hour",
                "Deploy Mandarin counter-narrative via RC WhatsApp groups"
            ]
        }
    ]
}
```

### 5.3 SSE Event Types (Web Dashboard)

| Event | Payload | Purpose |
|-------|---------|---------|
| `step` | `{id, status, data?}` | Processing step status (pending → running → done) |
| `source` | `{label, url, domain, credibility}` | Discovered source (live or RAG) |
| `result` | Full prediction response | Final predictions and historical patterns |
| `guard` | `{verdict, confidence}` | GUARD safety classification result |
| `misinfo` | `{detected, type, explanation}` | Misinformation detection result |
| `insights` | `{explanation}` | LLM-generated plain-language explanation |
| `error` | `{message}` | Pipeline error (non-fatal) |

---

## 6. Telegram Commands

| Command | Description | Mode |
|---------|-------------|------|
| `/start` | Welcome message with feature overview | Reactive |
| `/help` | Usage instructions for all modalities | Reactive |
| `/detect <text>` | Analyse inline text for AI generation | Reactive |
| `/research <query>` | Web research and summarisation | Reactive |
| `/predict <text>` | Rumour forecast from announcement text | **Proactive** |
| `/deploy` | Push last prediction's counter-narratives to community channels | **Proactive** |
| *(text message)* | Auto-detect and analyse | Reactive |
| *(photo)* | Image OCR + AI detection + manipulation | Reactive |
| *(voice note)* | Transcribe + detect + spoken verdict | Reactive |
| *(video)* | Frame + audio analysis | Reactive |

---

## 7. Demo Scenarios

### 7.1 DORSCON Orange (COVID-19, Feb 2020)

**Announcement:** MOH advisory raising DORSCON to Orange with precautionary measures.

**Predicted rumours (what actually happened):**
1. 🔴 **CRITICAL (92)** — "Sheng Siong and NTUC have run out of rice" → WhatsApp Mandarin groups → 2-4 hours
2. 🟠 **HIGH (87)** — "Toilet paper will be unavailable for weeks" → WhatsApp cross-language → 3-6 hours
3. 🟡 **MEDIUM (68)** — "Government is hiding real case counts" → Twitter/Reddit English → 4-8 hours

### 7.2 Nipah Virus Outbreak (Mar 2026)

**Announcement:** MOH advisory about potential Nipah virus cluster.

**Predicted rumours (forward-looking):**
1. 🔴 **CRITICAL (95)** — "Nipah is already spreading in dormitories"
2. 🔴 **CRITICAL (91)** — "Foreign workers are the source — avoid Little India"
3. 🟠 **HIGH (85)** — "Nipah is airborne and spreads through air conditioning"
4. 🟠 **HIGH (82)** — "Eat garlic and drink warm water to prevent Nipah"
5. 🟡 **MEDIUM (74)** — "The government is hiding fatalities"
6. 🟡 **MEDIUM (70)** — "Nipah vaccine exists but government won't distribute it"
7. 🔵 **LOW (55)** — "Nipah is a bioweapon from a foreign lab"
8. 🔵 **LOW (48)** — "Fruit bats are being released in Singapore parks"

---

## 8. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| **Detection latency** | < 5 seconds for text, < 10 seconds for image/audio |
| **Prediction latency** | < 15 seconds for full pipeline (SSE streams progress) |
| **Live API latency** | < 8 seconds for spoken verdict |
| **Availability** | Cloud Run auto-scaling, 0 → N instances |
| **Languages** | EN, ZH, MS, TA, Singlish (input) + EN/ZH/MS/TA (counter-narratives) |
| **Rate limiting** | Configurable per-user cooldown (default 3s) |
| **Privacy** | User IDs SHA-256 hashed before ClickHouse storage |
| **Data retention** | 90-day TTL on detection events |
| **Resilience** | All detection functions return structured dicts on failure — never raise |
| **API fallback** | Gemini → Groq automatic failover on any exception |

---

## 9. What MUST Work for Demo

- [x] Text detection with multilingual support
- [x] Image OCR + AI-signal detection + manipulation analysis
- [x] Voice note → spoken verdict via Gemini Live API
- [x] Video frame + audio analysis
- [x] SSE streaming in web dashboard
- [x] Cloud Run deployment (asia-southeast1)
- [ ] Rumour prediction from announcement input (Telegram + web)
- [ ] Counter-narrative generation in EN/ZH/MS/TA
- [ ] Telegram deployment of counter-narratives to community channels
- [ ] Demo scenario: DORSCON Orange predictions match real history
- [ ] RAG search over ClickHouse article_embeddings

---

## 10. What Does NOT Need to Work

- Real-time WhatsApp integration (deep links only)
- PDF announcement upload (text input is sufficient)
- PDF report export
- User authentication / role-based access
- Real-time collaborative editing of counter-narratives
- Community leader portal (separate page) — covered by Telegram deployment

---

*SENTINEL — Detect the threat. Predict the rumour. Protect the community.*

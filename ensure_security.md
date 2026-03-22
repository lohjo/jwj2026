# SENTINEL — Sinking Ship Audit & Hardening Plan

**Audit source:** [@Hartdrawss 20-point checklist](https://x.com/Hartdrawss/status/2035378419278532928)  
**Codebase:** `lohjo/jwj2026` — SENTINEL multimodal AI content detection platform  
**Date:** 2026-03-22

---

## Audit Results Summary

| # | Item | Status | Severity | File(s) |
|---|------|--------|----------|---------|
| 1 | Rate limiting on API routes | ❌ FAIL | CRITICAL | `app.py` |
| 2 | Auth tokens not in localStorage | ⚠️ WORSE — no auth at all | CRITICAL | `app.py`, `static/index.html` |
| 3 | Input sanitisation on forms | ❌ FAIL | CRITICAL | `app.py`, all pipeline entry points |
| 4 | No hardcoded API keys in frontend | ✅ PASS | — | `static/index.html` |
| 5 | Stripe webhook signature verification | ✅ N/A | — | No payments |
| 6 | Database indexing on queried fields | ⚠️ PARTIAL | HIGH | `db/sql/` |
| 7 | Error boundaries in the UI | ❌ FAIL | HIGH | `static/index.html` |
| 8 | Sessions that expire | ✅ N/A | — | No sessions |
| 9 | Pagination on database queries | ⚠️ PARTIAL | MEDIUM | `pipeline/rag.py`, `app.py` |
| 10 | Password reset link expiry | ✅ N/A | — | No auth system |
| 11 | Environment variable validation at startup | ⚠️ PARTIAL | HIGH | `config.py` |
| 12 | Images via CDN, not direct server | ⚠️ PARTIAL | MEDIUM | `app.py`, `static/` |
| 13 | CORS policy configured | ❌ FAIL | CRITICAL | `app.py` |
| 14 | Emails sent asynchronously | ✅ N/A | — | No email sending |
| 15 | Database connection pooling | ⚠️ PARTIAL | HIGH | `pipeline/logger.py`, `pipeline/guard.py`, `pipeline/translator.py` |
| 16 | Admin routes have role checks | ❌ FAIL | CRITICAL | `app.py` — all routes open |
| 17 | Health check endpoint | ✅ PASS | — | `app.py` `/health` exists |
| 18 | Structured logging in production | ⚠️ PARTIAL | HIGH | `telegram_bot.py`, `app.py` |
| 19 | Database backup strategy | ❌ FAIL | MEDIUM | `db/`, `research/skills/` |
| 20 | TypeScript on AI-generated code | ❌ FAIL | MEDIUM | `static/index.html` (2000+ lines vanilla JS) |

**Score: 4 PASS / 5 N/A / 4 PARTIAL / 7 FAIL**

---

## Tier 1 — CRITICAL (Ship is actively sinking — fix before any public launch)

### #1 — No Rate Limiting on API Routes

**Current state:**  
`telegram_bot.py` has `COOLDOWN_SECONDS=3.0` per user on Telegram handlers. The FastAPI app in `app.py` has **zero** rate limiting. Every route — `/analyse-stream`, `/analyse-audio`, `/analyse-image-stream`, `/research`, `/detect-video` — is open to unlimited requests.

**Blast radius:** Anyone can send thousands of requests per minute to `/analyse-audio`, triggering Gemini, Deepgram, and ElevenLabs API calls simultaneously. At Live API pricing, a sustained 60 req/min attack costs ~$500/hour.

**Implementation:**

```bash
pip install slowapi
```

**`app.py` — add rate limiting middleware:**

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply per route — differentiate by cost
@app.post("/analyse-stream")
@limiter.limit("20/minute;100/hour")    # cheap text — more generous
async def analyse_stream(request: Request, body: AnalyseStreamRequest): ...

@app.post("/analyse-audio")
@limiter.limit("5/minute;20/hour")       # expensive — Gemini Live API
async def analyse_audio(request: Request, file: UploadFile = File(...)): ...

@app.post("/analyse-image-stream")
@limiter.limit("10/minute;50/hour")
async def analyse_image_stream(request: Request, file: UploadFile = File(...)): ...

@app.post("/research")
@limiter.limit("5/minute;30/hour")       # Firecrawl + LLM — most expensive
async def research_endpoint(request: Request, body: ResearchRequest): ...
```

**`config.py` — add:**

```python
RATE_LIMIT_ENABLED = _optional_bool("RATE_LIMIT_ENABLED", True)
```

**`requirements.txt`:** Add `slowapi>=0.1.9`

---

### #2 & #16 — No Authentication on Web Dashboard (All Routes Public)

**Current state:**  
The FastAPI web dashboard has **no authentication whatsoever**. Every route in `app.py` is fully public — `/analyse-stream`, `/research`, `/detect-video`, `/ws/live-agent`. This means any internet user can use SENTINEL as a free proxy to your Gemini, Deepgram, ElevenLabs, and Firecrawl APIs.

Note: item #8 (sessions never expiring) is N/A because there are no sessions. Item #2 (tokens in localStorage) is N/A because there are no tokens. But the underlying issue — a completely open API — is far worse than either.

**Implementation (API key auth — appropriate for a demo/hackathon app):**

**`config.py` — add:**

```python
# Web dashboard API key — set a strong random value in .env
WEB_API_KEY = _optional("WEB_API_KEY", "")
WEB_AUTH_ENABLED = _optional_bool("WEB_AUTH_ENABLED", True)
```

**`app.py` — add a shared dependency:**

```python
from fastapi import Depends, HTTPException, Header
from config import WEB_API_KEY, WEB_AUTH_ENABLED

async def verify_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Dependency: require X-API-Key header on all mutating routes."""
    if not WEB_AUTH_ENABLED:
        return
    if not WEB_API_KEY:
        # No key configured → allow (dev mode)
        return
    if x_api_key != WEB_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# Apply to every route that calls external APIs:
@app.post("/analyse-stream", dependencies=[Depends(verify_api_key)])
@app.post("/analyse-audio", dependencies=[Depends(verify_api_key)])
@app.post("/analyse-image-stream", dependencies=[Depends(verify_api_key)])
@app.post("/research", dependencies=[Depends(verify_api_key)])
@app.post("/detect-video", dependencies=[Depends(verify_api_key)])
@app.post("/predict-stream", dependencies=[Depends(verify_api_key)])
```

**`static/index.html` — inject key from meta tag:**

```html
<!-- Set at server render time or via env -->
<meta name="api-key" content="{{ WEB_API_KEY }}">
```

```javascript
// Read once at startup — never store in localStorage
const API_KEY = document.querySelector('meta[name="api-key"]')?.content || '';

// Add to every fetch call:
headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY }
```

**`.env.example` — add:**

```env
WEB_API_KEY=your-strong-random-key-here   # generate: openssl rand -hex 32
WEB_AUTH_ENABLED=TRUE
```

**Cloud Run deploy** — add `--set-env-vars "WEB_API_KEY=$WEB_API_KEY"` to the deploy command in `cloudbuild.yaml`.

---

### #3 — No Input Sanitisation

**Current state:**  
`app.py` routes accept raw unbounded text and pass it directly to LLMs. `/analyse-stream` accepts any JSON body with no length cap. `/research` passes raw `query` to Firecrawl and then to `call_llm()`. There is no stripping of null bytes, control characters, or oversized payloads.

**Blast radius:**  
- Prompt injection via crafted input to `/analyse-stream` — attacker crafts text that overrides the detection prompt
- Resource exhaustion via 10MB text bodies sent to the LLM
- The `detect_misinformation` prompt interpolates `content[:2000]` — truncation is partial protection but not sanitisation

**Implementation:**

**`app.py` — add a shared sanitiser:**

```python
import re

MAX_TEXT_LENGTH  = 10_000   # chars — generous for detection, prevents abuse
MAX_QUERY_LENGTH = 500      # chars — research queries don't need more
MAX_FILE_SIZE_MB = 10

_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')

def sanitise_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Strip null bytes and control chars, enforce length cap."""
    if not isinstance(text, str):
        raise ValueError("text must be a string")
    text = _CONTROL_CHAR_RE.sub('', text)  # strip control characters
    text = text.strip()
    if len(text) > max_length:
        text = text[:max_length]
    return text

def validate_file_size(file: UploadFile, max_mb: int = MAX_FILE_SIZE_MB) -> None:
    """Reject files over the size limit before reading them."""
    # Check Content-Length header first (fast path)
    if hasattr(file, 'size') and file.size and file.size > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {max_mb}MB)")
```

**Apply at every entry point:**

```python
# In analyse_stream:
text = sanitise_text(body.text)
if not text:
    return JSONResponse(status_code=400, content={"error": "Text is required"})

# In research_endpoint:
query = sanitise_text(body.query, max_length=MAX_QUERY_LENGTH)

# In analyse_audio, analyse_image_stream, detect_video:
validate_file_size(file)
```

**`config.py` — externalise limits:**

```python
MAX_TEXT_LENGTH  = int(_optional("MAX_TEXT_LENGTH",  "10000"))
MAX_QUERY_LENGTH = int(_optional("MAX_QUERY_LENGTH", "500"))
MAX_FILE_SIZE_MB = int(_optional("MAX_FILE_SIZE_MB", "10"))
```

---

### #13 — No CORS Policy

**Current state:**  
`app.py` has no `CORSMiddleware`. Any website on the internet can make cross-origin requests to all SENTINEL API routes and WebSocket endpoints. A malicious page at `evil.com` can silently submit content for analysis using the visitor's browser, burning your API quota.

**Implementation:**

```bash
# Already in requirements.txt — fastapi includes starlette which includes CORSMiddleware
```

**`app.py` — add immediately after `app = FastAPI(...)`:**

```python
from fastapi.middleware.cors import CORSMiddleware
from config import CORS_ALLOWED_ORIGINS

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,     # see config below
    allow_credentials=True,
    allow_methods=["GET", "POST"],          # no PUT/DELETE/PATCH needed
    allow_headers=["Content-Type", "X-API-Key"],
    expose_headers=["Cache-Control"],
)
```

**`config.py` — add:**

```python
_cors_raw = _optional(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:8080,http://localhost:3000"
)
CORS_ALLOWED_ORIGINS: list[str] = [
    o.strip() for o in _cors_raw.split(",") if o.strip()
]
```

**`.env` — production:**

```env
CORS_ALLOWED_ORIGINS=https://sentinel-907933353915.asia-southeast1.run.app
```

**`.env` — local dev:**

```env
CORS_ALLOWED_ORIGINS=http://localhost:8080,http://localhost:3000
```

> ⚠️ **Do not use `allow_origins=["*"]`.** That defeats the purpose entirely. List only the exact origin(s) you control.

---

## Tier 2 — HIGH (Reliability failures — will hurt you at scale)

### #6 — Incomplete Database Indexing

**Current state:**  
`db/sql/01_detection_events.sql` uses `ORDER BY (user_id, timestamp)` — that's the ClickHouse primary index, which is good. But `article_embeddings` (the RAG table) has only `ORDER BY scraped_at`. The RAG queries filter on `hasAny(topics, ...)` and `cosineDistance(embedding, ...)` with **no secondary index**. At 10k+ articles this will do a full table scan on every prediction request.

**Implementation:**

**`db/sql/03_article_embeddings.sql` — add a skipping index:**

```sql
-- Add after the main CREATE TABLE
ALTER TABLE article_embeddings
    ADD INDEX idx_topics topics TYPE bloom_filter(0.01) GRANULARITY 1;

ALTER TABLE article_embeddings
    ADD INDEX idx_domain domain TYPE bloom_filter(0.01) GRANULARITY 1;

ALTER TABLE article_embeddings
    ADD INDEX idx_credibility credibility_score TYPE minmax GRANULARITY 4;
```

**`db/sql/01_detection_events.sql` — add a secondary index for dashboard queries:**

```sql
-- Fast lookup of harmful events by verdict
ALTER TABLE agent_logs.detection_events
    ADD INDEX idx_guard_verdict guard_verdict TYPE set(8) GRANULARITY 4;

ALTER TABLE agent_logs.detection_events
    ADD INDEX idx_is_harmful is_harmful TYPE minmax GRANULARITY 1;
```

> **Note:** ClickHouse skipping indexes don't enforce uniqueness — they allow the query engine to skip granules that definitely don't contain matching rows. The bloom filter is ideal for the `hasAny(topics, ...)` pattern.

---

### #7 — No Error Boundaries in the UI

**Current state:**  
`static/index.html` has try/catch inside individual async functions (`analyseTextStream`, `laConnect`, etc.) but no global error handler. An uncaught promise rejection in the PCMProcessor AudioWorklet or in `laDrawVisualizer`'s RAF loop will silently freeze the relevant UI section with zero user feedback.

**Implementation — add to `static/index.html` before closing `</script>`:**

```javascript
// ── Global error boundary ────────────────────────────────────────────
window.addEventListener('error', (event) => {
    console.error('[SENTINEL] Uncaught error:', event.error);
    _showGlobalError(`Unexpected error: ${event.message}. Please refresh the page.`);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('[SENTINEL] Unhandled promise rejection:', event.reason);
    // Don't surface every rejected promise — filter to meaningful ones
    const msg = event.reason?.message || String(event.reason);
    if (msg.includes('NetworkError') || msg.includes('Failed to fetch')) {
        _showGlobalError('Network error — check your connection and try again.');
    }
    event.preventDefault();  // suppress default console noise
});

function _showGlobalError(message) {
    // Find whatever panel is active and show an error banner
    const activePanel = document.querySelector('.panel.active');
    if (!activePanel) return;
    let banner = activePanel.querySelector('.global-error-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.className = 'global-error-banner';
        banner.style.cssText = [
            'background:var(--red-bg)', 'border:1px solid var(--red-border)',
            'border-left:3px solid var(--red)', 'padding:0.75rem 1rem',
            'border-radius:5px', 'margin-bottom:1rem', 'font-size:13px',
            'color:var(--red)', 'display:flex', 'align-items:center',
            'justify-content:space-between'
        ].join(';');
        activePanel.prepend(banner);
    }
    banner.innerHTML = `<span>⚠️ ${escapeHtml(message)}</span>
        <button onclick="this.parentElement.remove()" style="background:none;border:none;
        cursor:pointer;color:var(--red);font-size:16px;">×</button>`;
}
```

**Also wrap the AudioWorklet boot sequence** — if `addModule` fails (e.g. blob URL rejected by CSP), the mic silently stops working:

```javascript
// In laStartMic(), after the existing try/catch around addModule:
} catch(workletError) {
    logger.error('[Mic] AudioWorklet load failed:', workletError);
    _showGlobalError('Microphone setup failed — your browser may not support this feature.');
    laStopMic();
    return;
}
```

---

### #11 — Incomplete Environment Variable Validation

**Current state:**  
`config.py` has `_require()` which calls `sys.exit()` for missing required keys — that's correct. However:
- `CLICKHOUSE_PORT = int(_optional("CLICKHOUSE_PORT", "8443"))` — if someone sets `CLICKHOUSE_PORT=invalid`, this raises a bare `ValueError` at import time with no clear error message
- `COOLDOWN_SECONDS = float(_optional("COOLDOWN_SECONDS", "3.0"))` — same issue
- There is no validation that `GEMINI_MODEL` is a known valid model string

**Implementation — `config.py`:**

```python
def _optional_int(key: str, default: int) -> int:
    raw = os.getenv(key, str(default))
    try:
        return int(raw)
    except ValueError:
        sys.exit(f"[SENTINEL] Invalid value for {key}: '{raw}' (expected integer, got '{raw}')")

def _optional_float(key: str, default: float) -> float:
    raw = os.getenv(key, str(default))
    try:
        return float(raw)
    except ValueError:
        sys.exit(f"[SENTINEL] Invalid value for {key}: '{raw}' (expected float, got '{raw}')")

# Replace existing int/float conversions:
CLICKHOUSE_PORT              = _optional_int("CLICKHOUSE_PORT", 8443)
CLICKHOUSE_CONNECT_TIMEOUT   = _optional_int("CLICKHOUSE_CONNECT_TIMEOUT", 10)
CLICKHOUSE_SEND_RECEIVE_TIMEOUT = _optional_int("CLICKHOUSE_SEND_RECEIVE_TIMEOUT", 30)
CLICKHOUSE_MAX_RETRIES       = _optional_int("CLICKHOUSE_MAX_RETRIES", 1)
COOLDOWN_SECONDS             = _optional_float("COOLDOWN_SECONDS", 3.0)
LIVE_API_TIMEOUT_SECONDS     = _optional_float("LIVE_API_TIMEOUT_SECONDS", 20.0)
MAX_TEXT_LENGTH              = _optional_int("MAX_TEXT_LENGTH", 10000)
```

**Add a startup validation function** that runs eagerly and lists ALL missing/invalid vars at once (not one at a time via sys.exit):

```python
def validate_config() -> None:
    """Run all config checks at startup. Print all errors then exit once."""
    errors = []

    if GEMINI_MODEL and not GEMINI_MODEL.startswith("gemini-"):
        errors.append(f"GEMINI_MODEL='{GEMINI_MODEL}' doesn't look like a Gemini model ID")

    if CLICKHOUSE_PORT not in range(1, 65536):
        errors.append(f"CLICKHOUSE_PORT={CLICKHOUSE_PORT} is out of valid range 1–65535")

    if COOLDOWN_SECONDS < 0:
        errors.append(f"COOLDOWN_SECONDS={COOLDOWN_SECONDS} cannot be negative")

    if errors:
        for e in errors:
            print(f"[SENTINEL] Config error: {e}", file=sys.stderr)
        sys.exit(1)

# Call at the bottom of config.py:
validate_config()
```

---

### #15 — Unconfigured Connection Pooling

**Current state:**  
- `pipeline/logger.py` has a `_ch_client` singleton but it's never pinged to verify liveness and has no max pool size
- `pipeline/guard.py` creates a single `httpx.AsyncClient` with a 20-connection pool — that's actually fine
- `pipeline/translator.py` creates a **new** `httpx.AsyncClient` per translation call inside `async with httpx.AsyncClient(...)` — this means a new TCP connection is opened and closed for every single translation, which is very expensive under load

**Implementation:**

**`pipeline/translator.py` — use a module-level shared client:**

```python
# Module-level shared client — created once, reused across all translation calls
_translator_client: httpx.AsyncClient | None = None

def _get_translator_client() -> httpx.AsyncClient:
    global _translator_client
    if _translator_client is None or _translator_client.is_closed:
        _translator_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(
                max_connections=10,
                max_keepalive_connections=5,
                keepalive_expiry=30.0,
            ),
        )
    return _translator_client

# In _call_sealion_translate, replace `async with httpx.AsyncClient(...) as client:`
# with:
async def _call_sealion_translate(original_text: str, prompt: str) -> str:
    client = _get_translator_client()
    try:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        ...
    except Exception as e:
        logger.warning("SEA-LION translation failed: %s; returning original text", e)
        return original_text
```

**`pipeline/logger.py` — add liveness check to singleton:**

```python
def _get_ch_client():
    global _ch_client
    if _ch_client is not None:
        try:
            _ch_client.ping()   # lightweight: SELECT 1
            return _ch_client
        except Exception:
            logger.warning("[ClickHouse] Stale connection — reinitialising")
            _ch_client = None   # force re-init on next call

    if not CLICKHOUSE_HOST or not CLICKHOUSE_PASSWORD:
        return None
    try:
        import clickhouse_connect
        _ch_client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB,
            secure=True,
            connect_timeout=CLICKHOUSE_CONNECT_TIMEOUT,
            send_receive_timeout=CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
            query_retries=CLICKHOUSE_MAX_RETRIES,
            # Explicit pool sizing:
            compress=True,
        )
        return _ch_client
    except Exception:
        logger.exception("[ClickHouse] Failed to create client")
        return None
```

---

### #18 — No Structured Logging in Production

**Current state:**  
`logging.basicConfig(level=logging.INFO)` in `telegram_bot.py` — plain text logs to stdout. Cloud Run captures them, but Google Cloud Logging can't parse structured fields (request ID, user ID, severity) from unformatted strings. When something breaks, you can't filter by user, by content type, or by error type.

**Implementation — `config.py` — add:**

```python
LOG_LEVEL  = _optional("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = _optional("LOG_FORMAT", "json" if not os.getenv("LOCAL_DEV") else "text")
```

**Create `pipeline/logging_config.py`:**

```python
"""Structured logging setup — JSON in production, text in local dev."""

import logging
import json
import sys
from datetime import datetime, timezone
from config import LOG_LEVEL, LOG_FORMAT


class JsonFormatter(logging.Formatter):
    """Emit Cloud Logging-compatible JSON records."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "severity":   record.levelname,
            "message":    record.getMessage(),
            "logger":     record.name,
            "module":     record.module,
            "line":       record.lineno,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Forward any extra fields passed via logger.info("msg", extra={"user_id": ...})
        for key in ("user_id", "content_type", "request_id", "llm_used"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    handler = logging.StreamHandler(sys.stdout)

    if LOG_FORMAT == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
        ))

    logging.basicConfig(level=level, handlers=[handler], force=True)
    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
```

**`telegram_bot.py` and `app.py` — replace `logging.basicConfig(...)` with:**

```python
from pipeline.logging_config import configure_logging
configure_logging()
```

**`.env` — local dev:**

```env
LOG_FORMAT=text
LOCAL_DEV=1
LOG_LEVEL=DEBUG
```

**Cloud Run `.env` / `--set-env-vars`:**

```env
LOG_FORMAT=json
LOG_LEVEL=INFO
```

---

## Tier 3 — MEDIUM (Will hurt you at growth — fix before scaling)

### #9 — Missing Pagination on Database Queries

**Current state:**  
The ClickHouse RAG queries in `pipeline/rag.py` have `LIMIT 10` and `LIMIT 5` — those are fine. The detection events table has no query interface in the current API, so that's also fine for now. The real gap is `/research` — if `research_agent/agent.py` is ever exposed as a history endpoint, it reads all skill files with `SKILLS_DIR.glob("*.md")` with no pagination.

**Implementation (defensive — for future-proofing):**

**`pipeline/rag.py` — add explicit `OFFSET` support for future pagination:**

```python
async def search_rag(
    query_vector: list[float],
    topics: list[str],
    limit: int = 15,
    offset: int = 0,          # add pagination parameter
) -> list[dict]:
    # Pass limit and offset into the SQL queries
    ...
    LIMIT {limit} OFFSET {offset}
```

**`app.py` — add pagination params to the research endpoint:**

```python
class ResearchRequest(BaseModel):
    query: str
    page: int = 1          # 1-indexed
    page_size: int = 10    # max results per page

@app.post("/research")
async def research_endpoint(body: ResearchRequest):
    if body.page_size > 50:
        return JSONResponse(status_code=400, content={"error": "page_size max is 50"})
    ...
```

---

### #12 — No CDN for Static Assets

**Current state:**  
`static/index.html` (a 100KB+ file with inline CSS, inline JS, Google Fonts) is served directly from the Cloud Run container via FastAPI's `StaticFiles`. No cache headers, no CDN, no compression. Every page load fetches the full HTML from your Cloud Run instance in `asia-southeast1`.

**Implementation — two-step:**

**Step 1 — Add cache headers and compression to FastAPI (immediate):**

```python
# app.py — replace the StaticFiles mount with a cached version
from fastapi.responses import FileResponse
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.get("/", response_class=FileResponse)
async def serve_ui():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        return HTMLResponse("<h1>SENTINEL API</h1>")
    return FileResponse(
        index_path,
        headers={
            "Cache-Control": "public, max-age=300",  # 5-min cache — short for demo
            "X-Content-Type-Options": "nosniff",
        }
    )
```

**Step 2 — Cloud Run + Cloud CDN (production):**

Add to `cloudbuild.yaml` comments and deployment docs:
- Enable Cloud CDN on the Cloud Run service URL via Cloud Load Balancing
- Or upload `static/index.html` to Google Cloud Storage with a CDN bucket and serve from there
- Alternatively: self-host the Google Fonts by downloading them and serving from `/static/fonts/` — removes a third-party dependency and the DNS lookup penalty

---

### #19 — No Backup Strategy

**Current state:**  
ClickHouse Cloud has automatic backups (7-day retention on free tier), but this is undocumented, untested, and unmonitored. The `research/skills/` and `research/summaries/` directories contain generated content with no backup. A `gcloud run deploy` with a bad code change could wipe the Cloud Run container's filesystem (though it's stateless by design — this is actually fine for the container itself).

**Implementation:**

**ClickHouse — document and verify:**

```bash
# scripts/verify_backup.sh — run monthly
# Check backup exists in ClickHouse Cloud console:
# https://clickhouse.cloud/[org]/services/[service]/backups

# Test restore procedure (in a staging environment):
# 1. Create a restore from the most recent backup
# 2. Run: python db/run_sql.py db/sql/00_create_db.sql
# 3. Verify SELECT count() FROM agent_logs.detection_events returns expected count
```

**`research/` directory — add to `cloudbuild.yaml` as a Cloud Storage sync:**

```yaml
# In cloudbuild.yaml, add a backup step that runs on schedule
- name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
  id: backup-research
  entrypoint: bash
  args:
    - '-c'
    - |
      gsutil -m rsync -r gs://${PROJECT_ID}-sentinel-backups/research/ research/ || true
      # After deploy, sync research/ back to GCS
      gsutil -m rsync -r research/ gs://${PROJECT_ID}-sentinel-backups/research/
```

**`RUNBOOK.md` — create with:**

```markdown
## Disaster Recovery

### ClickHouse data loss
1. Go to ClickHouse Cloud console → Backups
2. Select most recent backup → Restore
3. Re-run `python db/run_sql.py` to ensure schema is current
4. Verify row counts match expected

### research/ directory loss  
1. `gsutil -m rsync -r gs://[project]-sentinel-backups/research/ research/`
2. Verify `research/skills/*.md` count matches expectation

### Full Cloud Run service loss
1. `bash setup-gcp.sh` to re-provision infrastructure
2. `gcloud builds submit --config cloudbuild.yaml` to rebuild and deploy
3. Set all Secret Manager secrets (see .env.example)
```

---

### #20 — No TypeScript on AI-Generated Frontend Code

**Current state:**  
`static/index.html` contains 2000+ lines of vanilla JavaScript with no type annotations. The PCMProcessor AudioWorklet was AI-generated with complex buffer arithmetic. The `InterruptibleLiveSession` interaction code, WebSocket state machine, and SSE parser are all untyped. `npm run build` doesn't exist — there is no build step.

A full TypeScript migration is out of scope for a hackathon project. The pragmatic middle path is **JSDoc type annotations + a TypeScript check pass** without a build step.

**Implementation — Phase 1 (JSDoc, no build step required):**

**Create `static/types.js` (or inline JSDoc at key functions):**

```javascript
/**
 * @typedef {Object} DetectionResult
 * @property {boolean|null} is_safe
 * @property {string} misinfo_type
 * @property {DetectionDetail} detection_result
 * @property {MisinfoResult} misinfo_result
 * @property {InsightsResult} insights_result
 * @property {string} source_lang
 */

/**
 * @typedef {Object} PipelineStep
 * @property {string} id
 * @property {'pending'|'running'|'done'} status
 * @property {*} [data]
 */

/**
 * @typedef {Object} VADState
 * @property {number} THRESHOLD
 * @property {number} FRAMES_TO_TRIGGER
 * @property {number} HOLD_FRAMES
 * @property {number} _activeCount
 * @property {number} _holdCount
 * @property {boolean} _triggered
 */

/** @type {VADState} */
const VAD = { ... };

/**
 * @param {Int16Array} int16Array
 * @returns {boolean}
 */
function detectVoiceActivity(int16Array) { ... }

/**
 * @param {DetectionResult} result
 * @returns {void}
 */
function showAnalysisResults(result) { ... }
```

**Add `jsconfig.json` at project root for IDE checking:**

```json
{
  "compilerOptions": {
    "checkJs": true,
    "strict": false,
    "noImplicitAny": false,
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "moduleResolution": "bundler"
  },
  "include": ["static/**/*.js", "static/**/*.html"]
}
```

**Phase 2 (future — when refactoring to a proper frontend build):**  
Migrate to Vite + TypeScript. The SSE consumer, WebSocket state machine, and PCMProcessor should be the first targets — they're the most complex and most likely to break silently.

---

## Items with No Action Required

| # | Item | Reason |
|---|------|--------|
| 4 | Hardcoded API keys in frontend | `static/index.html` has no hardcoded secrets. Keys are `.env` only. ✅ |
| 5 | Stripe webhook signature verification | No payment integration in SENTINEL. N/A |
| 8 | Sessions that never expire | No session management exists. The underlying concern (#2/#16) is addressed above. |
| 10 | Password reset link expiry | No authentication system, no passwords. N/A |
| 14 | Emails sent asynchronously | No email functionality in the codebase. N/A |
| 17 | Health check endpoint | `/health` endpoint exists in `app.py`. Returns `{"status":"healthy"}`. ✅ |

---

## Implementation Sequence

Execute in this order — later items depend on earlier ones being stable:

```
Week 1 — Stop the bleeding (Tier 1)
  [ ] #13  Add CORSMiddleware with explicit allowed origins
  [ ] #1   Add slowapi rate limiting to all API routes
  [ ] #3   Add sanitise_text() and validate_file_size() at all entry points
  [ ] #2   Add X-API-Key dependency + WEB_API_KEY to config and deploy
  [ ] #16  Apply auth dependency to all routes that call external APIs

Week 2 — Reliability (Tier 2)  
  [ ] #11  Replace bare int()/float() conversions with _optional_int/_optional_float
  [ ] #11  Add validate_config() startup check
  [ ] #18  Add JsonFormatter + configure_logging() in both app.py and telegram_bot.py
  [ ] #15  Refactor translator.py to use module-level shared httpx client
  [ ] #15  Add _ch_client.ping() liveness check in logger.py
  [ ] #7   Add window.onerror + unhandledrejection global error boundary in index.html
  [ ] #6   Add ClickHouse skipping indexes for article_embeddings and detection_events

Week 3 — Resilience (Tier 3)
  [ ] #19  Create RUNBOOK.md with disaster recovery steps
  [ ] #19  Add gsutil backup sync step to cloudbuild.yaml
  [ ] #12  Add GZipMiddleware + cache headers to static file serving
  [ ] #9   Add offset parameter to rag.py queries + page param to /research
  [ ] #20  Add JSDoc types to key functions + jsconfig.json
```

---

## Files Modified Summary

| File | Changes |
|------|---------|
| `app.py` | CORSMiddleware, slowapi rate limiting, X-API-Key auth dependency, sanitise_text(), GZipMiddleware |
| `config.py` | `_optional_int`, `_optional_float`, `CORS_ALLOWED_ORIGINS`, `WEB_API_KEY`, `WEB_AUTH_ENABLED`, `validate_config()` |
| `pipeline/logging_config.py` | **NEW** — JsonFormatter, configure_logging() |
| `pipeline/translator.py` | Module-level shared httpx client |
| `pipeline/logger.py` | `_ch_client.ping()` liveness check |
| `static/index.html` | Global error boundary, VAD debounce (from CODEBASE_TRIAGE), JSDoc types |
| `static/types.js` | **NEW** — JSDoc typedef declarations |
| `db/sql/03_article_embeddings.sql` | Add bloom filter skipping indexes |
| `db/sql/01_detection_events.sql` | Add set() and minmax skipping indexes |
| `jsconfig.json` | **NEW** — checkJs config for IDE |
| `RUNBOOK.md` | **NEW** — disaster recovery procedures |
| `cloudbuild.yaml` | Add GCS backup sync step |
| `requirements.txt` | Add `slowapi>=0.1.9` |
| `.env.example` | Add `WEB_API_KEY`, `CORS_ALLOWED_ORIGINS`, `LOG_FORMAT`, `LOG_LEVEL` |

---

*Built for SENTINEL — Gemini Live Agent Challenge 2026.*
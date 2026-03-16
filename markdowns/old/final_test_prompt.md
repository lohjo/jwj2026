# SENTINEL — Final Integration Test & Fix Prompt
# Run this prompt in Claude Code from the project root.
# Goal: everything passes, Docker runs, Cloud Run hosts, all detections work.

---

## YOUR ROLE

You are performing a final pre-submission integration test and fix pass on SENTINEL.
Work through every step in order. Do not skip steps. Fix every failure at root cause —
never patch tests to hide bugs.

---

## STEP 0 — READ PROJECT CONTEXT FIRST

Before touching any file, read:
- `CLAUDE.md` — canonical rules and architecture
- `ARCHITECTURE.md` — module graph and flow
- `pipeline/detector.py` — full file, focus on detect_misinformation()
- `pipeline/insights.py` — full file, focus on call_llm()
- `media/live.py` — full file if it exists

---

## STEP 1 — FIX KNOWN ERROR: JSON Parse Failure in detect_misinformation()

The following error is confirmed in production logs:

```
[Misinformation] Detection failed: Unterminated string starting at: line 3 column 26 (char 62)
json.decoder.JSONDecodeError: Unterminated string starting at: line 3 column 26
```

### Root cause

The LLM response contains a JSON string with an unescaped special character —
most likely a quote `"` or newline `\n` inside a string value that breaks
`json.loads()`. The current regex strip only removes markdown fences but does
not handle truncated or malformed JSON.

### Fix to apply in `pipeline/detector.py`

Replace the current JSON parsing block in `detect_misinformation()` with this
robust parser:

```python
import json
import re

def _safe_json_parse(raw: str, fallback: dict) -> dict:
    """
    Robustly parse LLM JSON output.
    Handles: markdown fences, truncated strings, unescaped quotes,
    trailing commas, and single-quoted keys.
    Never raises — returns fallback on any failure.
    """
    if not raw:
        return fallback

    # Step 1: strip markdown code fences
    clean = re.sub(
        r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE
    ).strip()

    # Step 2: attempt direct parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    # Step 3: extract JSON object/array using brace matching
    try:
        start = clean.index('{')
        # find the last valid closing brace
        depth = 0
        end = start
        for i, ch in enumerate(clean[start:], start):
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        extracted = clean[start:end + 1]
        return json.loads(extracted)
    except (ValueError, json.JSONDecodeError):
        pass

    # Step 4: truncation repair — add closing brace if string ends mid-object
    try:
        # Count unclosed braces and add them
        open_braces = clean.count('{') - clean.count('}')
        open_brackets = clean.count('[') - clean.count(']')
        repaired = clean
        # Close any open string (find last unmatched quote)
        if repaired.count('"') % 2 != 0:
            repaired += '"'
        repaired += ']' * open_brackets + '}' * open_braces
        return json.loads(repaired)
    except (ValueError, json.JSONDecodeError):
        pass

    # All recovery attempts failed
    logging.warning(f"[JSON] All parse attempts failed. Raw: {raw[:200]}")
    return fallback
```

Apply `_safe_json_parse()` to ALL three functions that parse LLM JSON:
- `detect_misinformation()` in `pipeline/detector.py`
- `detect_image_manipulation()` in `media/image.py`
- Any other function calling `json.loads()` on LLM output

Pattern for each:
```python
# BEFORE (brittle)
clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
return json.loads(clean)

# AFTER (robust)
return _safe_json_parse(raw, FALLBACK)
```

Also fix the upstream prompt to reduce truncation risk — add a max_tokens
guard and instruct the model to always close JSON:

```python
prompt = f"""...
CRITICAL: Return valid, complete JSON only. 
Do not truncate. Close all brackets and braces.
Do not use quotes inside string values — use single quotes or rephrase.
...
"""
```

Verify fix:
```bash
.venv\Scripts\python.exe -c "
from pipeline.detector import _safe_json_parse
# Test truncated JSON
result = _safe_json_parse('{\"detected\": true, \"explanation\": \"test', {})
print('Truncation recovery:', result)
# Test unescaped quote
result = _safe_json_parse('{\"detected\": false, \"explanation\": \"it\'s fine\"}', {})
print('Quote recovery:', result)
"
```

---

## STEP 2 — FIX: App runs uvicorn instead of telegram_bot.py

The logs show:
```
INFO: Uvicorn running on http://0.0.0.0:8080
INFO: "GET / HTTP/1.1" 200 OK
INFO: "POST /analyse-stream HTTP/1.1" 200 OK
INFO: "WebSocket /ws/live-audio" [accepted]
```

This means the container is running a **FastAPI/uvicorn app**, not the
Telegram bot polling loop. The `docker-compose.yml` command overrides
the Dockerfile CMD with:
```yaml
command: python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

### Decision: keep both — uvicorn serves the Live API web frontend + API,
telegram bot runs as a background thread.

Check if `app.py` at project root is a FastAPI app. If yes, confirm it:
1. Starts the Telegram bot polling in a background thread on startup
2. Exposes `/analyse-stream`, `/detect-image`, and `/ws/live-audio`
3. Has a `/health` endpoint for Cloud Run health checks

If `app.py` does NOT start the Telegram bot, add this to `app.py`:

```python
# app.py — top of file after imports
import threading
from telegram_bot import start_bot

def _start_telegram_bot():
    """Run Telegram bot polling in background thread."""
    try:
        start_bot()
    except Exception as e:
        logging.error(f"Telegram bot crashed: {e}")

# Start bot when FastAPI app initialises
@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_thread = threading.Thread(target=_start_telegram_bot, daemon=True)
    bot_thread.start()
    logging.info("Telegram bot polling started in background thread")
    yield
    logging.info("Shutting down")

app = FastAPI(lifespan=lifespan)
```

Verify `docker-compose.yml` CMD is correct:
```yaml
command: python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

This should start uvicorn (which starts FastAPI, which starts the Telegram
bot thread). Confirm by checking logs for BOTH:
```
INFO: Uvicorn running on http://0.0.0.0:8080   ← FastAPI up
INFO: Starting Telegram bot polling...          ← Bot up
```

---

## STEP 3 — FIX: WebSocket /ws/live-audio closes immediately

The logs show:
```
INFO: "WebSocket /ws/live-audio" [accepted]
INFO: connection open
INFO: connection closed
```

Connection opens and closes instantly — this means either:
1. The WebSocket handler crashes on the first await
2. No audio data arrives before a timeout
3. The Gemini Live API session fails to open

### Check `app.py` WebSocket handler

Read the `/ws/live-audio` handler in full. Common causes:

```python
# Likely bug — unhandled exception closes the WebSocket silently
@app.websocket("/ws/live-audio")
async def live_audio_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        audio_bytes = await websocket.receive_bytes()  # ← crashes if client sends text first
        result = await live.live_voice_exchange(audio_bytes)
        await websocket.send_bytes(result)
    except Exception as e:
        logging.error(f"[WS] Error: {e}")
        # ← missing: await websocket.close() with error code
```

### Fix pattern

```python
@app.websocket("/ws/live-audio")
async def live_audio_ws(websocket: WebSocket):
    await websocket.accept()
    logging.info("[WS /ws/live-audio] Connection accepted")
    try:
        # Receive audio bytes from browser
        data = await asyncio.wait_for(
            websocket.receive_bytes(),
            timeout=30.0  # don't wait forever
        )
        logging.info(f"[WS] Received {len(data)} bytes audio")

        # Parse optional context from query params
        context = websocket.query_params.get("context", "")

        # Call Gemini Live API
        reply_ogg = await live.live_voice_exchange(
            audio_bytes=data,
            mime_type="audio/ogg",
            system_context=context,
        )

        if reply_ogg:
            await websocket.send_bytes(reply_ogg)
            logging.info(f"[WS] Sent {len(reply_ogg)} bytes reply")
        else:
            # Live API failed — send JSON error so client can fall back
            await websocket.send_text(
                '{"error": "Live API unavailable", "fallback": true}'
            )

    except asyncio.TimeoutError:
        logging.warning("[WS] Client did not send audio within 30s")
        await websocket.send_text('{"error": "timeout"}')
    except Exception as e:
        logging.exception(f"[WS] Unhandled error: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
        logging.info("[WS /ws/live-audio] Connection closed")
```

---

## STEP 4 — RUN FULL TEST SUITE

```bash
.venv\Scripts\python.exe -m pytest tests/ -v --tb=short 2>&1
```

For every failing test:
1. Read the exact failure
2. Fix the root cause in source code
3. Re-run that test file
4. Only move on when it passes

Target: all tests pass. Baseline from CHANGELOG.md: 52 passed.

If `tests/test_live.py` does not exist, create it per the pattern in `implementation.md`.

---

## STEP 5 — DOCKER END-TO-END TEST

### 5.1 Build and start

```bash
docker compose down --remove-orphans
docker compose up --build 2>&1
```

### 5.2 Check for these exact log lines within 30 seconds of startup

```
INFO: Uvicorn running on http://0.0.0.0:8080       ✅ FastAPI up
INFO: Starting Telegram bot polling...              ✅ Bot up
```

If either is missing, read the container logs:
```bash
docker compose logs web --tail 50
```

Fix root cause before continuing.

### 5.3 Test every HTTP endpoint

```bash
# Health check
curl -s http://localhost:8080/health
# Expected: {"status": "ok"} or 200

# Root
curl -s http://localhost:8080/
# Expected: 200

# Text detection
curl -s -X POST http://localhost:8080/analyse-stream \
  -H "Content-Type: application/json" \
  -d '{"text": "This article claims that scientists have discovered a cure for cancer using common household items."}' 
# Expected: JSON with detection fields, no 500 error

# Image detection  
curl -s -X POST http://localhost:8080/detect-image \
  -F "file=@tests/fixtures/test_image.jpg"
# Expected: JSON with manipulation_detected field
```

### 5.4 Test WebSocket Live API

```bash
# Install wscat if not present
npm install -g wscat

# Test WebSocket connection stays open
wscat -c ws://localhost:8080/ws/live-audio
# Expected: connection stays open waiting for input
# NOT: immediate "connection closed"
```

### 5.5 Confirm JSON error is fixed

```bash
curl -s -X POST http://localhost:8080/analyse-stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Breaking: \"Prime Minister\" announces free money scheme via WhatsApp. Share now!"}'
# Expected: JSON response with no JSONDecodeError in docker logs
```

Watch docker logs while running:
```bash
docker compose logs web -f
```

Zero `JSONDecodeError` lines should appear.

---

## STEP 6 — DETECTION PIPELINE INTEGRATION TEST

Run each detection function directly to verify they all work end-to-end:

```bash
.venv\Scripts\python.exe -c "
import asyncio
import logging
logging.basicConfig(level=logging.INFO)

async def run_all():
    from pipeline import guard, detector, insights, translator, formatter

    test_text = 'Breaking news: Singapore government announces free SG1000 voucher for all citizens. WhatsApp this link to claim.'

    print('\n=== 1. Language Detection ===')
    lang = translator.detect_language(test_text)
    print(f'Language: {lang}')
    assert lang == 'en', f'Expected en, got {lang}'

    print('\n=== 2. GUARD Detection ===')
    guard_result = await guard.run_guard_detection(test_text)
    print(f'Label: {guard_result[\"label\"]}')
    print(f'Confidence: {guard_result[\"confidence\"]}')
    assert guard_result['label'] not in ('detection_failed',), \
        f'GUARD returned legacy error label: {guard_result[\"label\"]}'

    print('\n=== 3. Misinformation Detection ===')
    misinfo_result = await detector.detect_misinformation(
        test_text, context_description='text message'
    )
    print(f'Detected: {misinfo_result[\"misinformation_detected\"]}')
    print(f'Type: {misinfo_result[\"misinformation_type\"]}')
    assert 'misinformation_detected' in misinfo_result, 'Missing key'
    assert 'explanation' in misinfo_result, 'Missing explanation'

    print('\n=== 4. Insights / call_llm ===')
    from pipeline.insights import call_llm
    response = await call_llm('In one sentence, what is 2+2?')
    print(f'LLM response: {response[:100]}')
    assert response, 'call_llm returned empty string — check GEMINI_API_KEY'

    print('\n=== 5. run_insights (full) ===')
    result = await insights.run_insights(
        test_text,
        guard_result,
        misinformation_result=misinfo_result,
    )
    print(f'Explanation: {result[\"explanation\"][:150]}')
    assert result['explanation'], 'Empty explanation'

    print('\n=== 6. format_detection_message ===')
    from pipeline.formatter import format_detection_message
    msg = format_detection_message({
        **guard_result,
        **misinfo_result,
        'explanation': result['explanation'],
    })
    assert '<b>' in msg or '<i>' in msg or '✅' in msg or '🤖' in msg, \
        'Output does not look like HTML'
    assert 'MarkdownV2' not in msg, 'MarkdownV2 syntax found in HTML output'
    print(f'Formatted (first 200 chars): {msg[:200]}')

    print('\n=== 7. Multilingual: Chinese input ===')
    zh_text = '紧急通知：新加坡政府宣布派发1000元现金券，立即点击链接领取。'
    lang_zh = translator.detect_language(zh_text)
    print(f'Detected language: {lang_zh}')
    if lang_zh != 'en':
        en_text = await translator.translate_to_english(zh_text, lang_zh)
        print(f'Translated: {en_text[:100]}')
        assert en_text, 'Translation returned empty'

    print('\n=== ALL DETECTION TESTS PASSED ===')

asyncio.run(run_all())
"
```

---

## STEP 7 — CLOUD RUN DEPLOYMENT TEST

### 7.1 Deploy

```bash
$PROJECT_ID = $(gcloud config get-value project)
$REGION = "asia-southeast1"

gcloud run deploy sentinel `
  --source . `
  --region $REGION `
  --platform managed `
  --allow-unauthenticated `
  --memory 2Gi `
  --cpu 2 `
  --timeout 300 `
  --port 8080 `
  --project $PROJECT_ID
```

### 7.2 Get URL and verify

```bash
$URL = $(gcloud run services describe sentinel `
  --region $REGION `
  --format="value(status.url)" `
  --project $PROJECT_ID)

Write-Host "Cloud Run URL: $URL"

# Health check against live URL
curl -s "$URL/health"

# Text detection against live URL
curl -s -X POST "$URL/analyse-stream" `
  -H "Content-Type: application/json" `
  -d '{"text": "Free iPhone giveaway! Send this to 10 friends to claim."}'
```

### 7.3 Verify bot started on Cloud Run

```bash
gcloud logging read `
  "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" `
  --limit 30 `
  --format="table(timestamp,textPayload)" `
  --project $PROJECT_ID
```

Must find this line:
```
Starting Telegram bot polling...
```

If it says `uvicorn` started but no bot line appears, the background thread
is not being started — revisit Step 2.

### 7.4 Test Telegram bot is live on Cloud Run

Open Telegram, find your bot, send:
- A text message → should receive HTML detection verdict
- A voice note → should receive a voice note reply (Gemini Live API)
- A photo → should receive image manipulation result

---

## STEP 8 — SECRET MANAGER VERIFICATION

Confirm no plaintext secrets remain in Cloud Run env:

```bash
gcloud run services describe sentinel `
  --region asia-southeast1 `
  --format="get(spec.template.spec.containers[0].env)" `
  --project $PROJECT_ID
```

Every sensitive key must show:
```
valueFrom.secretKeyRef.name: TELEGRAM_TOKEN
valueFrom.secretKeyRef.key: latest
```

NOT:
```
value: 7762861118:AAFPjaNznG0x...   ← FAIL: plaintext in env
```

If any plaintext values remain, remove them and set via Secret Manager
per the sequence in the previous session.

---

## STEP 9 — FINAL COMPLIANCE CHECKLIST

Work through every item. Fix any ❌ before marking as complete.

```
DOCKER
[ ] docker compose up --build completes with no errors
[ ] http://localhost:8080/health returns 200
[ ] http://localhost:8080/analyse-stream returns detection JSON
[ ] ws://localhost:8080/ws/live-audio stays open (does not close immediately)
[ ] No JSONDecodeError in docker compose logs
[ ] Telegram bot polling starts in container logs

DETECTION PIPELINE
[ ] run_guard_detection() returns label in {ai_generated, human_generated, inconclusive, api_error, timeout, api_key_missing}
[ ] run_guard_detection() NEVER returns label="detection_failed"
[ ] detect_misinformation() returns structured dict, never raises
[ ] detect_image_manipulation() returns structured dict, never raises
[ ] call_llm() falls back to Groq on ANY Gemini exception
[ ] call_llm() returns "" when both Gemini and Groq fail (never raises)
[ ] run_insights() receives english_text — not detection_result["label"]
[ ] format_detection_message() output contains HTML — no MarkdownV2

ARCHITECTURE RULES
[ ] Zero os.getenv() calls outside config.py
[ ] Zero parse_mode="MarkdownV2" anywhere
[ ] Zero clickhouse_driver imports
[ ] Zero genai.configure() or GenerativeModel() calls
[ ] All temp files deleted in finally blocks

CLOUD RUN
[ ] gcloud run services describe sentinel returns active URL
[ ] /health endpoint returns 200 on live URL
[ ] Bot polling confirmed in Cloud Run logs
[ ] All secrets via Secret Manager refs — zero plaintext values in env

TESTS
[ ] pytest tests/ -v → all pass, 0 failures
[ ] tests/test_live.py exists and passes
[ ] test_guard covers api_error, timeout, api_key_missing labels
[ ] test_insights covers Groq fallback and never-raises behaviour
[ ] test_logger confirms never raises and uses async_insert=1

HACKATHON SUBMISSION
[ ] media/live.py exists with genai-2.0-flash-live-001 WebSocket session
[ ] cloudbuild.yaml committed to repo
[ ] .env is in .gitignore
[ ] README.md has spin-up instructions
[ ] GitHub repo is public
```

---

## STEP 10 — OUTPUT FINAL REPORT

After completing all steps, output:

```markdown
## SENTINEL FINAL TEST REPORT

### Docker
- Build: PASSED / FAILED
- Uvicorn: PASSED / FAILED
- Telegram bot thread: PASSED / FAILED
- WebSocket: PASSED / FAILED
- JSON parse error: FIXED / STILL PRESENT

### Detection Pipeline
- GUARD: PASSED / FAILED (label: ___)
- Misinformation: PASSED / FAILED
- Image manipulation: PASSED / FAILED
- call_llm Groq fallback: PASSED / FAILED
- Multilingual (ZH): PASSED / FAILED

### Cloud Run
- Deployment: PASSED / FAILED
- URL: https://...
- Health check: PASSED / FAILED
- Bot polling in logs: PASSED / FAILED
- Secrets via Secret Manager: PASSED / FAILED

### Tests
- Total: N passed, N failed
- New tests added: N

### Files modified this session
[list]

### Remaining issues (if any)
[list with priority]
```
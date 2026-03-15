

Let me explore the current codebase state and the commands directory to build an accurate plan. 

Explore codebase for Live API and GCP state

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands)

Searched for files matching `**/Dockerfile`, no matches

Searched for files matching `**/.gcloudignore`, no matches

Searched for files matching `**/cloudbuild.yaml`, no matches

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/verify-hackathon.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/config.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/requirements.txt)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/deploy-gcp.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/live-api.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/config.py#50-50), lines 50 to 129

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/media/live.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/insights.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/media/audio.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/detector.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/media/image.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/add-detection-module.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/telegram_bot.py#1-1), lines 1 to 600

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/a2a-integrate.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/detection-audit.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/telegram_bot.py#600-600), lines 600 to 680

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/workshop-patterns.md#1-1), lines 1 to 300

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.env.example)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/telegram-audit.md)

Searched for files matching `**/pydub`, no matches

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/guard.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/translator.py#1-1), lines 1 to 100

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/logger.py#1-1), lines 1 to 100

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/pipeline/formatter.py#1-1), lines 1 to 100

Searched for files matching `**/verify_hackathon.py`, no matches

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026)

Read [](file:///c%3A/Users/Admin/AppData/Roaming/Code/User/workspaceStorage/926030e64172d40001505d4745fed331/GitHub.copilot-chat/chat-session-resources/eca1bd6c-1531-43aa-8fa1-07647b6f69b3/toolu_vrtx_01HrB6PTguip9zZFcoqZ2Cf5__vscode-1773570012050/content.txt#1-1), lines 1 to 200

Now let me read the commands files that define the hackathon requirements: 

Searched for files matching `**/.claude/commands/*.md`, 8 matches

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/live-api.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/deploy-gcp.md)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/.claude/commands/verify-hackathon.md)

Now let me read the current state of the key files that need modification:   

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/config.py#1-1), lines 1 to 80

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/media/live.py)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/requirements.txt)

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/telegram_bot.py#560-560), lines 560 to 680

Searched for text `handle_audio` (`**/telegram_bot.py`), 3 results

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/telegram_bot.py#437-437), lines 437 to 560

Now let me check if there are existing test files for live.py and the `bootstrap_retries` setting:  

Searched for text `bootstrap_retries` (`**/telegram_bot.py`), no results

Searched for files matching `**/tests/test_live*`, no matches

Let me check the top of telegram_bot.py for imports and existing `run_polling` config:  

Read [](file:///c%3A/Users/Admin/source/repos/jwj2026/telegram_bot.py#1-1), lines 1 to 60

Searched for text `run_polling` (`**/telegram_bot.py`), 1 result

Now I have a complete picture. Let me also check if there's an existing Dockerfile or .gcloudignore:     

Searched for files matching `**/Dockerfile`, no matches

Searched for files matching `**/.gcloudignore`, no matches

Searched for files matching `**/cloudbuild.yaml`, no matches

Searched for text `live` (`**/telegram_bot.py`), 1 result

Good — `media.live` is not imported anywhere in telegram_bot.py yet. Now I have the full picture. Let me save the plan. 

Created memory file [](file:///c%3A/Users/Admin/AppData/Roaming/Code/User/workspaceStorage/926030e64172d40001505d4745fed331/GitHub.copilot-chat/memory-tool/memories/ZWNhMWJkNmMtMTUzMS00M2FhLThmYTEtMDc2NDdiNmY2OWIz/plan.md)

## Plan: Gemini Live API + GCP Cloud Run Deployment

SENTINEL currently fails three critical hackathon requirements: no Live API (WebSocket), no GCP hosting, and no deployment proof. This plan covers implementing both in strict order — Phase 1 (Live API) then Phase 2 (Cloud Run).

---

### Phase 1 — Gemini Live API Integration

**Step 1.1: Add config constants** — config.py
- Add `GEMINI_LIVE_MODEL = _optional("GEMINI_LIVE_MODEL", "gemini-2.0-flash-live-001")` and `GEMINI_LIVE_VOICE = _optional("GEMINI_LIVE_VOICE", "Aoede")` after line 48 (after the existing `GEMINI_MODEL` declaration)

**Step 1.2: Add `pydub` dependency** — requirements.txt
- Add `pydub>=0.25.1` (needed for PCM16→OGG conversion). `google-genai` already present.

**Step 1.3: Implement live.py** — live.py *(done)*
- `async def live_voice_exchange(audio_bytes, mime_type, system_context) -> bytes` — main function
- `def _pcm_to_ogg(pcm_bytes, sample_rate) -> bytes` — converter helper
- Uses `genai.Client(api_key=GEMINI_API_KEY).aio.live.connect()` WebSocket (not REST)
- `LiveConnectConfig` with `response_modalities=["AUDIO"]`, voice from config
- `SENTINEL_LIVE_PERSONA` system instruction with `{detection_context}` slot
- Sends audio via `LiveClientRealtimeInput`, signals `end_of_turn=True`
- Collects PCM chunks from `session.receive()`, converts to OGG via pydub
- Returns `b""` on ANY exception — never raises
- Full spec in CLAUDE.md section "Gemini Live API — live.py" + audit checklist in live-api.md

**Step 1.4: Wire into `handle_audio`** — telegram_bot.py *(depends on 1.3)*
- Add `from media.live import live_voice_exchange` at telegram_bot.py
- After current Step 6 (translate back) and before Step 7 (format text), insert:
  1. Read `audio_bytes` from downloaded file
  2. Build `detection_context` string from `results` dict (GUARD verdict + misinfo + explanation)
  3. Call `reply_ogg = await live_voice_exchange(audio_bytes, "audio/ogg", detection_context)`
  4. If `reply_ogg` → write to temp file → `update.message.reply_voice()`
  5. If empty → fall through to existing text reply (Step 7) + ElevenLabs TTS (Step 8)
- Add `reply_ogg_path` to the `finally` cleanup block

**Step 1.5: Fix `run_polling()`** — telegram_bot.py
- Change `app.run_polling()` → `app.run_polling(bootstrap_retries=5)`

**Step 1.6: Create tests** — `tests/test_live.py` *(new file, parallel with 1.4)*
- `test_live_voice_exchange_returns_ogg_on_success` — mock `genai.Client` + `aio.live.connect`
- `test_live_voice_exchange_returns_empty_on_failure` — mock exception, assert `b""`
- `test_pcm_to_ogg_returns_empty_on_empty_input` — assert `_pcm_to_ogg(b"") == b""`
- No real WebSocket connections

**Step 1.7: Verify** *(depends on all above)*
- `pytest tests/test_live.py -v` — 3 tests pass
- `pytest tests/ -v` — no regressions
- Import check: `from media.live import live_voice_exchange`
- Grep: `live_voice_exchange` appears in telegram_bot.py

---

### Phase 2 — GCP Cloud Run Deployment

**Step 2.1: Create `Dockerfile`** *(parallel with 2.2)*
- `python:3.11-slim`, install `ffmpeg` + OpenCV system deps
- Non-root user, `ENV PORT=8080`, `CMD ["python", "telegram_bot.py"]`

**Step 2.2: Create `.gcloudignore`** *(parallel with 2.1)*
- Exclude `.env`, `.venv/`, __pycache__, `downloads/`, tests, .claude, `*.md` (keep README.md)

**Step 2.3: Create `cloudbuild.yaml`** *(parallel with 2.1)*
- Build → push → deploy to Cloud Run (`asia-southeast1`, 2Gi, 2 CPU, 300s timeout)
- Bonus points for automated CI/CD

**Step 2.4: GCP prerequisites** *(user action)*
- `gcloud auth login`, set project, set region `asia-southeast1`
- Enable APIs: `run`, `cloudbuild`, `artifactregistry`, `aiplatform`

**Step 2.5: Deploy** *(depends on 2.1–2.4, user action)*
- `gcloud run deploy sentinel --source . --region asia-southeast1 --memory 2Gi --cpu 2 --timeout 300`
- Pass all env vars via `--set-env-vars` (including `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_VOICE`)

**Step 2.6: Verify deployment** *(depends on 2.5, user action)*
- `gcloud run services describe sentinel --region asia-southeast1` → live URL
- Check logs for "Starting Telegram bot polling..."

**Step 2.7: Record deployment proof** *(depends on 2.6, user action)*
- Screen capture of Cloud Run console showing "Serving" status

---

### Relevant Files
- config.py — add 2 constants (lines ~48-49)
- live.py — implement from scratch (~100 lines)
- telegram_bot.py — import + modify `handle_audio` + fix `run_polling`
- requirements.txt — add `pydub>=0.25.1`
- `tests/test_live.py` — new test file
- `Dockerfile` — new file
- `.gcloudignore` — new file
- `cloudbuild.yaml` — new file (bonus)

### Verification
1. `pytest tests/test_live.py -v` — 3 tests pass
2. `pytest tests/ -v --tb=short` — full suite, no regressions
3. `python -c "from config import GEMINI_LIVE_MODEL; print(GEMINI_LIVE_MODEL)"` → `gemini-2.0-flash-live-001`
4. `grep -rn "live_voice_exchange" telegram_bot.py` → found in `handle_audio`
5. `grep -rn "bootstrap_retries" telegram_bot.py` → `bootstrap_retries=5`
6. `docker build -t sentinel .` → builds without errors
7. Post-deploy: `gcloud run services describe sentinel` → live URL
8. E2E: send voice note to bot → receive spoken verdict back

### Decisions
- Live API is PRIMARY audio response path; ElevenLabs stays as fallback when `live_voice_exchange` returns `b""`
- `_format_context_for_live()` is a local helper in telegram_bot.py (not in `formatter.py`)
- ClickHouse port kept at 8443 (current working config), not changed to 8123
- Dockerfile uses non-root user for security
- `cloudbuild.yaml` included for bonus points

### Further Considerations
1. **ffmpeg** must be installed locally for pydub tests — `winget install ffmpeg` if missing
2. **Test audio fixture** (`tests/fixtures/test_audio.ogg`) doesn't exist — unit tests use mocks so this only matters for optional manual E2E testing
3. **`.env` additions**: user should add `GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001` and `GEMINI_LIVE_VOICE=Aoede` (or rely on config.py defaults)
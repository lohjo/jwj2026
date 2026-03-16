# Changelog

## Hackathon Compliance & Workshop Patterns (2026-03-16)

### Summary
This release brings SENTINEL to full hackathon compliance, applies workshop patterns from the Google Multimodal Agent Workshop, and updates all markdown documentation to reflect the current architecture.

### Hackathon compliance fixes
- Fixed `verify_hackathon.py` to accept both `end_of_turn` and `turn_complete` signalling keywords — resolves 2 false FAIL checks.
- Added `GEMINI_LIVE_MODEL`, `GEMINI_LIVE_VOICE`, and Vertex AI entries to `.env.example`.
- Fixed `GEMINI_MODEL` default in `.env.example` from `gemini-1.5-flash` to `gemini-2.5-flash`.

### Workshop pattern implementations
- **Dockerfile hardening** (Pattern 5): Added `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `--no-install-recommends`, and `HEALTHCHECK` directive.
- **Cloud Build modernisation** (Pattern 6): Migrated `cloudbuild.yaml` from `gcr.io` to Artifact Registry, added dual tagging (`BUILD_ID` + `latest`), step IDs with `waitFor` dependencies, container labels, and substitution variables.
- **GCP bootstrap script** (Pattern 8): Added `setup-gcp.sh` — idempotent script that enables required GCP APIs and creates the Artifact Registry repository.

### Documentation updates
- `ARCHITECTURE.md`: Added Gemini Live API section, updated model registry to current models (`gemini-2.5-flash`, `gemini-2.5-flash-native-audio-latest`), added `media/live.py` to dependency graph and flow diagram, added workshop patterns compliance notes.
- `CONTRIBUTING.md`: Added Live API testing rules, Dockerfile/cloudbuild best practices, GCP setup guidance, and `verify_hackathon.py` to PR checklist.
- `CHANGELOG.md`: Added this release entry.

## Refactor Release (2026-03-10)

### Summary
This release completes the SENTINEL architecture refactor from a mixed legacy layout to a modular pipeline-based layout. The runtime now follows the structure defined in `CLAUDE.md` and enforces consistent detection, translation, logging, and fallback behavior.

### Architecture changes
- Replaced monolithic legacy orchestration with dedicated modules:
  - `../../pipeline/` for detection, translation, formatting, logging, and LLM routing
  - `../../media/` for image, audio, and video analysis
  - `../../research_agent/` for Firecrawl-powered web research and caching
- Rewrote `../../telegram_bot.py` as handlers-only orchestration.
- Centralized environment access in `../../config.py`.

### SDK consistency stack
- Added/used root `../../CLAUDE.md` as persistent project instructions for Claude SDK behavior alignment.
- Added `../../pipeline/sdk_runner.py` as the singleton SDK execution wrapper.
- Added `SENTINEL_APPEND_PROMPT` in `../../config.py` for deterministic behavioral rules.
- Added `../../verify_sdk_consistency.py` checks to verify config, runner, and instruction stack.

### Detection pipeline changes
- `../../pipeline/guard.py`: standardized SEA-LION GUARD integration with dict-based fallbacks.
- `../../pipeline/detector.py`: GUARD + misinformation + manipulation orchestration with `asyncio.gather`.
- `../../pipeline/insights.py`: unified `call_llm()` path with Gemini primary and Groq fallback.
- `../../pipeline/translator.py`: strict language detect and EN bridge flow.
- `../../pipeline/formatter.py`: HTML-only response formatting.
- `../../pipeline/logger.py`: non-blocking ClickHouse logging with async insert settings.

### Media and speech changes
- `../../media/audio.py` updated for current Deepgram SDK path:
  - `client.listen.v1.media.transcribe_file(...)`
- ElevenLabs TTS path standardized for multilingual voice output.
- Media handlers enforce safe cleanup and fallback return behavior.

### Research changes
- Replaced ad hoc crawling approach with Firecrawl integration:
  - `../../research_agent/crawler.py` uses Firecrawl endpoints and `onlyMainContent=true`.
- Added summarization and skill cache workflow:
  - `../../research_agent/summariser.py`
  - `../../research_agent/skill_cache.py`
  - `../../research_agent/agent.py`

### Logging and data changes
- Standardized ClickHouse usage via `clickhouse-connect` only.
- Insert behavior uses async settings:
  - `async_insert=1`
  - `wait_for_async_insert=0`
- Logging functions are fail-safe and do not raise into Telegram handlers.

### Tests
- Added/updated the focused test suite:
  - `../../tests/test_guard.py`
  - `../../tests/test_insights.py`
  - `../../tests/test_translator.py`
  - `../../tests/test_formatter.py`
  - `../../tests/test_audio.py`
  - `../../tests/test_logger.py`
  - `../../tests/test_research_agent.py`
- Current status: `52 passed`.

### Removed legacy files and modules
- Removed legacy detector modules:
  - `../../image_detector.py`
  - `../../text_detector.py`
  - `../../detect_cli.py`
  - `../../ocr.py`
  - `../../web_crawler.py`
- Removed legacy ADK code files:
  - `../../ai_agent_adk/agent.py`
  - `../../ai_agent_adk/tools.py`
  - `../../ai_agent_adk/translator.py`
  - `../../ai_agent_adk/chat-cli.py`
  - `../../ai_agent_adk/__init__.py`
  - `../../ai_agent_adk/fix.md`
  - `../../ai_agent_adk/INSTRUCTIONS.md`
  - `../../ai_agent_adk/INTEGRATION.md`
  - `../../ai_agent_adk/memory.md`
- Removed superseded research agent internals:
  - `../../research_agent/fetcher.py`
  - `../../research_agent/deduplicator.py`

### Breaking changes
- Legacy imports targeting `ai_agent_adk.tools` no longer work.
- Root markdown prompts were moved into `../old/` and are no longer canonical runtime docs.
- Deepgram transcription call path changed to v6-style API.
- Detection and translation utilities now enforce strict dict fallback contracts instead of exception propagation.

### Migration notes
- Use `../../config.py` constants instead of calling `os.getenv()` in feature modules.
- Route all LLM calls through `../../pipeline/insights.py::call_llm()`.
- Keep `../../CLAUDE.md` at project root; do not move or rename it.

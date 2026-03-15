# Detection Pipeline Audit

Audit the full SENTINEL detection pipeline for correctness, resilience, and
compliance with CLAUDE.md rules. Use this before any major pipeline change
or when debugging inconclusive verdicts.

## Areas to Audit

### Pipeline flow correctness
Verify the translation flow in every handler follows the exact order from CLAUDE.md:
`detect_language → translate_to_english → guard + misinfo + manipulation (asyncio.gather)
→ call_llm → translate_from_english → format_detection_message → reply`

For each handler, check:
- [ ] detect_language called with len(text) >= 20 guard
- [ ] translate_to_english skipped when source_lang == "en"
- [ ] asyncio.gather used for guard + misinfo (and manipulation for images)
- [ ] run_insights receives actual content — not GUARD label string
- [ ] translate_from_english skipped when source_lang == "en"
- [ ] parse_mode="HTML" on every reply_text call
- [ ] Temp files deleted in finally block

### Guard detection (`pipeline/guard.py`)
- [ ] Never returns `label: "detection_failed"` — only `api_error | timeout | api_key_missing`
- [ ] Raw response logged before parsing: `logging.info(f"[GUARD] Raw: {raw_text[:200]}")`
- [ ] Verdict parsing covers all patterns: AI-generated, human-generated, inconclusive
- [ ] asyncio.TimeoutError caught separately → `label: "timeout"`
- [ ] Missing API key checked before HTTP call → `label: "api_key_missing"`

### Insights (`pipeline/insights.py`)
- [ ] call_llm() is the only entry point for LLM calls
- [ ] Gemini uses `genai.Client(api_key=GEMINI_API_KEY).models.generate_content()` — not old SDK
- [ ] Groq fallback triggers on ANY Gemini exception — not just quota errors
- [ ] Both Gemini and Groq fail → returns `""` (never raises)
- [ ] run_insights() accepts misinformation_result=None and manipulation_result=None
- [ ] guard_context skipped when label is in {"api_error", "timeout", "api_key_missing"}

### Misinformation detection (`pipeline/detector.py`)
- [ ] detect_misinformation() exists
- [ ] Returns structured dict on failure — never raises
- [ ] Called concurrently with guard via asyncio.gather
- [ ] JSON response stripped of markdown fences before parsing

### Image manipulation (`media/image.py`)
- [ ] detect_image_manipulation() exists
- [ ] Uses genai.Client() — not old genai.configure()
- [ ] Returns structured dict on failure — never raises
- [ ] Called via asyncio.gather in handle_photo

### Logger (`pipeline/logger.py`)
- [ ] Uses clickhouse-connect — not clickhouse-driver
- [ ] Port 8123, secure=True
- [ ] async_insert=1, wait_for_async_insert=0
- [ ] Never raises under any circumstance

## Output format

For each check:
- ✅ if passing
- ❌ file:line + exact issue + one-line fix

Then produce a ranked fix list (P0 = breaks verdicts, P1 = feature gap, P2 = violation).

## Specific debugging: inconclusive verdicts

If the bot is returning inconclusive verdicts, check in this order:
1. Is GUARD returning `label: "detection_failed"` or an error label?
   → If yes: fix GUARD error handling first
2. Is run_insights receiving the GUARD label string as `content`?
   → If yes: fix the caller to pass `english_text` not `detection_result["label"]`
3. Is the SEA-LION API returning 401?
   → If yes: fix OPENAI_API_KEY in .env
4. Is Gemini returning 400 API_KEY_INVALID?
   → If yes: fix GEMINI_API_KEY in .env (it's probably still the placeholder)

## Arguments

$ARGUMENTS

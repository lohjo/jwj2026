# Telegram Bot Audit

Audit `telegram_bot.py` for correctness, obsolete code, and compliance with
CLAUDE.md rules. Based on analysis of the node-telegram-bot-api reference repo
and the SENTINEL architecture.

## What to audit

Read `telegram_bot.py` in full, then work through every section below.
Report ✅ / ❌ + file:line for each item. Fix every ❌ found.

---

## Section A — Legacy / Obsolete Code

These patterns were found in the legacy `telegram_bot.py` and must not exist
in the refactored version:

```
[ ] import from ai_agent_adk.tools or ai-agent-adk
      Reason: ai_agent_adk/ was deleted per CHANGELOG.md
      Fix: import from pipeline.* and media.* instead

[ ] from image_detector import detect_fake_text
      Reason: image_detector.py was deleted per CHANGELOG.md
      Fix: remove; use media.image.detect_image_manipulation()

[ ] importlib.import_module('ai_agent_adk.tools') with fallback path loading
      Reason: legacy shim for deleted module — dead code
      Fix: delete the entire try/except import block

[ ] getattr(tools_module, 'detect_language', None) style dynamic imports
      Reason: all functions now live in named pipeline/* modules
      Fix: use direct imports from pipeline.translator, pipeline.guard, etc.

[ ] detect_fake_text() calls as fallback in handle_text
      Reason: legacy detector — function no longer exists
      Fix: remove; pipeline.detector.run_full_detection() is the only path

[ ] main_cli() function
      Reason: CLI mode was for the legacy text_detector.py workflow
      Fix: remove unless a specific CLI use case is documented in CLAUDE.md

[ ] bootstrap_retries default (0 or not set) on app.run_polling()
      Reason: 0 retries = instant crash on any startup network failure
      Fix: app.run_polling(bootstrap_retries=5)
```

---

## Section B — Handler compliance (CLAUDE.md rules)

For each handler — `handle_text`, `handle_photo`, `handle_audio`, `handle_video`:

```
[ ] parse_mode="HTML" on every reply_text / reply_voice call
      Never: parse_mode="Markdown" or parse_mode="MarkdownV2"

[ ] detect_language() called with len(text) >= 20 guard
      If text < 20 chars: skip detect_language, default source_lang = "en"

[ ] translate_to_english() only called when source_lang != "en"

[ ] asyncio.gather() used for concurrent detections (not sequential await)
      handle_text:  asyncio.gather(guard, misinfo)
      handle_photo: asyncio.gather(guard, misinfo, manipulation)

[ ] run_insights() receives english_text — NOT detection_result["label"]

[ ] translate_from_english() only called when source_lang != "en"

[ ] format_detection_message() called to build the reply — no inline HTML string building

[ ] log_to_clickhouse() called via asyncio.create_task(asyncio.to_thread(...))
      Never: await log_to_clickhouse() — must be fire-and-forget

[ ] Temp files (audio, images) deleted in finally blocks
      Pattern: try: ... finally: if os.path.exists(path): os.remove(path)
```

---

## Section C — Session and rate limiting

```
[ ] InMemorySessionService imported from google.adk.sessions
      (or equivalent — confirm ADK is the right source for this)

[ ] get_or_create_session() uses app_name matching CLAUDE.md APP_NAME constant

[ ] check_rate_limit() uses COOLDOWN_SECONDS from config.py
      Never: hardcoded 3.0 — must use config.COOLDOWN_SECONDS

[ ] user_last_request and user_sessions are module-level dicts
      Confirm: not recreated per-request
```

---

## Section D — Bot startup

```
[ ] TELEGRAM_TOKEN loaded from config.py (not os.environ.get directly in telegram_bot.py)
      Exception: config.py itself reads os.getenv() — that is correct

[ ] ApplicationBuilder().token(TELEGRAM_TOKEN).build() pattern used

[ ] All four handlers registered:
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
      MessageHandler(filters.PHOTO, handle_photo)
      MessageHandler(filters.VOICE | filters.AUDIO, handle_audio)
      MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video)

[ ] /research command handler registered (research_agent.agent.research)

[ ] /start or /help command handler exists with HTML-formatted response

[ ] bootstrap_retries=5 on run_polling()
```

---

## Section E — Deprecated Telegram API patterns

Based on node-telegram-bot-api analysis — Python equivalent patterns to avoid:

```
[ ] No positional argument-style bot method calls (use keyword args)
      Bad:  bot.send_message(chat_id, text)
      Good: bot.send_message(chat_id=chat_id, text=text)

[ ] No raw reply_markup strings — always use ReplyKeyboardMarkup/InlineKeyboardMarkup objects

[ ] Voice notes sent via reply_voice(voice=open(..., "rb")) pattern
      Not: reply_document() for voice — Telegram treats these differently

[ ] No hardcoded file_id strings in tests — mock the bot object entirely
```

---

## Output format

For each section, produce:

```markdown
### Section A — Legacy / Obsolete Code
| Item | Status | Location | Fix applied |
|---|---|---|---|
| ai_agent_adk import | ❌ | line 45 | Removed entire import block |
| ...
```

Then list all changes made as a minimal diff.

---

## Arguments

$ARGUMENTS

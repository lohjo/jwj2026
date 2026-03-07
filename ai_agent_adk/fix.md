# fix.md — Telegram Bot Error Fixes

## Errors

```
INFO:root:Runner not available; skipping translation to English
[WARN] run_guard_detection received non-English input: et
INFO:httpx:HTTP Request: POST https://api.sea-lion.ai/v1/chat/completions "HTTP/1.1 401 Unauthorized"
INFO:httpx:HTTP Request: POST https://api.sea-lion.ai/v1/chat/completions "HTTP/1.1 401 Unauthorized"
```

---

## Root Causes

| Error | Cause |
|---|---|
| `Runner not available` | Runner fetched via `getattr(context, 'adk_runner', None)` but never attached to Telegram `context` — always `None` |
| `401 Unauthorized` | `tools.py` has its own `load_dotenv()` resolving relative to its own path, missing project root `.env` — API key never reaches the SEA-LION client |
| `non-English input: et` | `langdetect` misidentifies short strings — "et" (Estonian) is a false positive on inputs under ~20 characters |

---

## Fix 1 — Initialise ADK Runner at module level

The runner is never created — `getattr(context, 'adk_runner', None)` always returns `None`
because nothing attaches it to the Telegram context object.

Add a module-level runner factory in `telegram_bot.py` after the session service is defined:

```python
from google.adk.runners import Runner

# Module-level runner — initialised once, reused across all handlers
_runner: Runner | None = None

def get_runner() -> Runner | None:
    global _runner
    if _runner is None:
        try:
            from ai_agent_adk.agent import root_agent
            _runner = Runner(
                app_name=APP_NAME,
                agent=root_agent,
                session_service=session_service,
            )
        except Exception:
            logging.exception("Failed to initialise ADK runner")
    return _runner
```

---

## Fix 2 — Replace both `getattr(context, 'adk_runner', None)` usages

There are two occurrences in `handle_text` — one for `translate_to_english` and one for
`translate_from_english`. Replace both:

```python
# BEFORE — never finds the runner
runner = getattr(context, 'adk_runner', None)

# AFTER — uses module-level runner
runner = get_runner()
```

---

## Fix 3 — Force `.env` to load before tools module reads API keys

`tools.py` loads its own `load_dotenv()` relative to its file location, not the project root.
By the time `tools.py` is imported, the API key may not be in `os.environ` yet.

Update the top of `telegram_bot.py` to use `override=True` and fail fast if the key is missing:

```python
# Force load project root .env into os.environ before any module reads API keys
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)

# Fail fast if API key is missing — prevents silent 401s downstream
if not os.environ.get("OPENAI_API_KEY"):
    logging.error("OPENAI_API_KEY not found in .env — SEA-LION API calls will fail with 401")
    sys.exit(1)
```

The `override=True` ensures the correct key propagates even if `tools.py` already called
`load_dotenv()` with the wrong path first.

---

## Fix 4 — Guard against `langdetect` false positives on short strings

`langdetect` is unreliable on inputs under ~20 characters and commonly misidentifies short
English text as other languages (e.g. "et" for Estonian). Add a minimum length check:

```python
# BEFORE — detects language regardless of input length
source_lang = detect_language(raw_text)

# AFTER — skip detection on short strings, default to English
if detect_language is not None and len(raw_text) >= 20:
    source_lang = detect_language(raw_text)
else:
    source_lang = "en"
```

---

## Summary of Changes in `telegram_bot.py`

| Location | Change |
|---|---|
| Top of file, after imports | Add `override=True` to `load_dotenv()` + `OPENAI_API_KEY` fail-fast check |
| After `session_service` definition | Add `_runner` global + `get_runner()` factory function |
| `handle_text` — translate_to_english block | Replace `getattr(context, 'adk_runner', None)` with `get_runner()` |
| `handle_text` — translate_from_english block | Replace `getattr(context, 'adk_runner', None)` with `get_runner()` |
| `handle_text` — language detection block | Add `len(raw_text) >= 20` guard before calling `detect_language` |

---

## Expected Log After Fix

```
INFO:root:Loaded .env from: C:\Users\...\AI-Fake-Detector\.env
INFO:root:ADK runner initialised successfully
INFO:httpx:HTTP Request: POST https://api.sea-lion.ai/v1/chat/completions "HTTP/1.1 200 OK"
```
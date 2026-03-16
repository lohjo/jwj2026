# Plan: Multilingual Detection with SEA-LION Gemma

## Objective
Update the language detection and translation pipeline so that:
1. `detect_language` constrains output to four supported languages: **English, Mandarin Chinese (Simplified), Malay, Tamil**
2. Bot responses are translated back to the user's detected language
3. All translation uses the **SEA-LION Gemma** model (`aisingapore/Gemma-SEA-LION-v3-9B-IT`) via the OpenAI-compatible API at `api.sea-lion.ai`

---

## Changes Made

### 1. `ai_agent_adk/tools.py` — `detect_language()`
- **Before**: Returned raw `langdetect` ISO code (could be any of 50+ languages)
- **After**: Maps detected language to one of `en`, `zh`, `ms`, `ta`
  - Added `SUPPORTED_LANGS` set, `_LANG_MAP` dict, and `LANG_NAMES` dict
  - Indonesian (`id`) maps to Malay (`ms`) as the closest supported language
  - Chinese variants (`zh-cn`, `zh-tw`, `zh-hk`) all map to `zh`
  - Unsupported languages default to `en`

### 2. `ai_agent_adk/tools.py` — `translate_to_english()` & `translate_from_english()`
- **Before**: Depended on Google ADK Runner + translator subagent (required runner, user_id, session_id)
- **After**: Calls SEA-LION Gemma model directly via `httpx` POST to `{OPENAI_API_BASE}/chat/completions`
  - Model: `TRANSLATOR_MODEL` env var (default: `aisingapore/Gemma-SEA-LION-v3-9B-IT`)
  - Backward-compatible signature — `runner`, `user_id`, `session_id` params kept but unused
  - Shared helper `_call_sealion_translate()` handles API call, error fallback
  - System prompts enforce:
    - **To English**: preserve original phrasing exactly (for detection accuracy)
    - **From English**: natural translation, preserve technical terms (`AI-generated`, `deepfake`, etc.)

### 3. `ai_agent_adk/translator.py` — Unchanged
- The translator subagent still exists for ADK agent orchestration use cases
- Direct API translation in `tools.py` is independent and self-contained

---

## Supported Language Matrix

| Code | Language                     | Detect | Translate To EN | Translate From EN |
|------|------------------------------|--------|-----------------|-------------------|
| `en` | English                      | ✅      | N/A (no-op)     | N/A (no-op)       |
| `zh` | Mandarin Chinese (Simplified)| ✅      | ✅               | ✅                 |
| `ms` | Malay                        | ✅      | ✅               | ✅                 |
| `ta` | Tamil                        | ✅      | ✅               | ✅                 |

---

## Pipeline Flow

```
User sends message (any supported language)
   │
   ├─ detect_language(text) → "en" | "zh" | "ms" | "ta"
   │
   ├─ if not "en": translate_to_english(text)  ← SEA-LION Gemma
   │
   ├─ run_guard_detection(english_text)         ← SEA-LION GUARD
   ├─ detect_misinformation(english_text)       ← Gemini
   ├─ run_insights(english_text, results)       ← Gemini
   │
   ├─ format_detection_response(results)
   │
   ├─ if not "en": translate_from_english(response) ← SEA-LION Gemma
   │
   └─ Send response to user in their language
```

---

## Configuration

| Env Variable       | Default                                   | Purpose                  |
|--------------------|--------------------------------------------|--------------------------|
| `OPENAI_API_BASE`  | `https://api.sea-lion.ai/v1`               | SEA-LION API endpoint    |
| `OPENAI_API_KEY`   | *(required)*                               | API authentication       |
| `TRANSLATOR_MODEL` | `aisingapore/Gemma-SEA-LION-v3-9B-IT`      | Translation model        |
| `MODEL`            | `aisingapore/Llama-SEA-LION-v3-70B-IT`     | Main agent model         |
| `GUARD_MODEL`      | `aisingapore/SEA-Guard`                    | GUARD detection model    |

---

## Verification Checklist
- [ ] `detect_language` returns only `en`, `zh`, `ms`, `ta`
- [ ] Chinese text detected as `zh`
- [ ] Malay/Indonesian text detected as `ms`
- [ ] Tamil text detected as `ta`
- [ ] Translation to English works without ADK runner
- [ ] Translation from English works without ADK runner
- [ ] Backward-compatible call signature preserved
- [ ] Existing tests still pass

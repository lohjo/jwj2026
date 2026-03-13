# Contributing

## Scope
This guide covers contribution rules for the refactored SENTINEL codebase.

## Critical code rules
- Use `parse_mode="HTML"` for Telegram replies. Do not use MarkdownV2.
- Use `clickhouse-connect` only. Do not add `clickhouse-driver`.
- Wrap all external API calls in `try/except`.
- Detection and translation helpers must return dict-based fallbacks on failure.
- Delete temporary media files in `finally` blocks.
- Apply `len(text) >= 20` before running language detection logic.
- Wrap blocking SDK/file/database calls with `asyncio.to_thread()` in async paths.

Reference: `../../CLAUDE.md`

## Dependency rule
- `../../config.py` is the only file that may call `os.getenv()`.
- All other modules must import constants from `config.py`.

## Architecture boundaries
- `../../telegram_bot.py` contains handlers and orchestration only.
- Business logic belongs in `../../pipeline/`, `../../media/`, and `../../research_agent/`.
- All LLM calls must go through `../../pipeline/insights.py::call_llm()`.

## Translation rules
- Pre-detection translation (non-English to English): preserve exact phrasing.
- Post-detection translation (English to user language): fluent natural translation.
- Keep terms in English: `AI-generated`, `deepfake`, `GUARD`, `OCR`, `confidence score`.
- For audio, use Deepgram `detected_language`.

## How to add a new detection module
1. Add a focused module under `../../pipeline/` or `../../media/`.
2. Ensure the module returns structured fallback dicts on all failures.
3. Integrate it into `../../pipeline/detector.py` orchestration.
4. Keep handler logic in `../../telegram_bot.py` thin.
5. Add a dedicated test file under `../../tests/` and mock all external APIs.

## Testing requirements
- Add tests for every non-trivial function.
- Mock all external providers (Gemini, Groq, Deepgram, ElevenLabs, Firecrawl, ClickHouse).
- Keep logger behavior non-raising in tests.
- Use pytest async support for async functions.

Run tests:
```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

## Pull request checklist
- Code follows `CLAUDE.md` rules.
- No new direct env reads outside `config.py`.
- No new direct LLM calls outside `pipeline/insights.py`.
- Tests added or updated.
- `tests/` suite passes locally.
- Markdown documentation links and code fences are valid.

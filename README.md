# AI Content Detection — First Release

Description
- Short: A pragmatic AI content detection toolkit and Telegram bot that analyses text, images, audio, and video for likely AI-generation signals. Core orchestration lives in the Telegram handler and the ADK-based agent pipeline. See [telegram_bot.py](telegram_bot.py) and [ai_agent_adk/agent.py](ai_agent_adk/agent.py).
- Focus: a defensible detection flow (OCR → language detection → translate → GUARD detection → explanation) that pairs model APIs (Gemini / SEA-LION) with deterministic media processing.

Interesting techniques
- **Async pipelines**: handlers use Python `async`/`await` to keep I/O (HTTP, file downloads, transcription) non-blocking — see Python asyncio docs: https://docs.python.org/3/library/asyncio.html
- **Shared async HTTP client**: a single `httpx.AsyncClient` is reused for connection pooling, sensible timeouts and efficient concurrency: https://www.python-httpx.org/
- **Multimodal orchestration**: images use Gemini for captioning + OCR while audio uses Deepgram for STT; these signals are fused into a single detection input.
- **Safe translation bridge**: explicit detect → translate-to-English → detect → translate-back flow via an ADK translator subagent to match model assumptions.
- **Background telemetry**: non-blocking logging (e.g., ClickHouse) is scheduled via `asyncio.create_task` and thread offload to avoid response latency.
- **Transient storage + cleanup**: downloaded media are stored in a local `downloads/` folder with explicit cleanup to avoid disk growth.
- **Lightweight rate-limiting & session reuse**: per-user cooldowns and an `InMemorySessionService` are used to avoid repeated heavy initialisation.
- **Model/tool compatibility layers**: the repo contains shims for Gemma-style and reasoning models and builds tool schemas for function-calling integrations.

Non-obvious technologies & libraries
- google-genai / Gemini — Google GenAI client for image/text multimodal analysis: https://developers.generativeai.google
- google-adk — ADK `Agent` and `Runner` usage for subagents and tool orchestration (see `ai_agent_adk/agent.py`).
- python-telegram-bot — async Telegram bot framework used for handlers and polling: https://docs.python-telegram-bot.org/
- httpx — async HTTP client for robust, async-friendly requests and connection pooling: https://www.python-httpx.org/
- deepgram-sdk — speech-to-text (Nova models) for reliable audio transcription: https://developers.deepgram.com/
- elevenlabs — text-to-speech for optional voice replies: https://github.com/elevenlabs/elevenlabs-python
- opencv-python-headless — image/frame processing in headless servers: https://pypi.org/project/opencv-python-headless/
- pydub — convenient audio extraction and format handling for video workflows: https://github.com/jiaaro/pydub
- imagehash — perceptual hashing helpers for image-similarity checks: https://pypi.org/project/ImageHash/
- langdetect — language detection used to gate translation and detection steps: https://pypi.org/project/langdetect/
- python-dotenv — local `.env` loading: https://pypi.org/project/python-dotenv/

External links
- `python-telegram-bot`: https://docs.python-telegram-bot.org/
- `google genai / Gemini`: https://developers.generativeai.google
- `httpx`: https://www.python-httpx.org/
- `deepgram`: https://developers.deepgram.com/
- `elevenlabs`: https://github.com/elevenlabs/elevenlabs-python
- `opencv-python-headless`: https://pypi.org/project/opencv-python-headless/
- `Pillow`: https://pillow.readthedocs.io/
- `pydub`: https://github.com/jiaaro/pydub
- `langdetect`: https://pypi.org/project/langdetect/
- `imagehash`: https://pypi.org/project/ImageHash/
- `python-dotenv`: https://pypi.org/project/python-dotenv/

Project structure
```
ai_agent_adk/
tests/
```
- `ai_agent_adk/`: agent bootstrap, tool definitions and translator subagent. Contains the ADK `Agent`/`Runner` wiring, model-tool schema builders, and multimodal wrappers used at runtime.
- `tests/`: pytest tests that exercise bot message formatting and media handlers.
- Implied runtime folders: `downloads/` (created at runtime for temporary media), and other transient folders produced during processing (e.g., temp audio exports).

Key files
- Bot & orchestration: [telegram_bot.py](telegram_bot.py)
- Text detector: [text_detector.py](text_detector.py)
- Agent bootstrap: [ai_agent_adk/agent.py](ai_agent_adk/agent.py)
- Tooling & integrations: [ai_agent_adk/tools.py](ai_agent_adk/tools.py)
- OCR/video glue: [ocr.py](ocr.py)

Notes
- No web fonts or frontend assets are referenced by the codebase.
- Licensing: no `LICENSE` file detected — add one if you intend to publish this project.

If you want additional sections (Security considerations, Contributing, or a short example configuration snippet), say which and I will add them.

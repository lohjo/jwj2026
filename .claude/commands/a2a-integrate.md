# A2A Protocol Integration

Implement or audit Agent-to-Agent (A2A) protocol integration in SENTINEL.
A2A is a Linux Foundation open standard (v1.0.0) that allows AI agents from
different frameworks to communicate as peers via a well-defined HTTP + SSE interface.

Reference: https://github.com/google/A2A

## What A2A Adds to SENTINEL

SENTINEL currently uses internal `asyncio.gather` for multi-agent coordination.
A2A replaces or extends this with a **standardised external agent interface** so
SENTINEL can:
- Expose its detection pipeline as a callable A2A agent (other agents send it content)
- Call external A2A-compatible agents (e.g. a specialised deepfake detector, a
  fact-checker, a translation service) without custom integration code
- Participate in multi-agent workflows where agents discover each other via
  `AgentCard` at `/.well-known/agent-card.json`

---

## Step 1 — Install the A2A Python SDK

```bash
.venv\Scripts\pip install a2a-sdk
# or if not yet published:
.venv\Scripts\pip install git+https://github.com/google-a2a/a2a-python.git
```

Verify:
```python
import a2a
print(a2a.__version__)
```

---

## Step 2 — Define SENTINEL's AgentCard

Create `a2a_card.py` at project root. This is the self-description other agents
use to discover SENTINEL's capabilities.

```python
# a2a_card.py
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

SENTINEL_AGENT_CARD = AgentCard(
    name="SENTINEL",
    description=(
        "Multimodal AI-generated content detection agent. "
        "Analyses text, images, audio, and video for AI generation signals, "
        "misinformation, and manipulation. Supports EN, ZH, MS, TA, Singlish."
    ),
    url="https://your-cloud-run-url/a2a",   # update after GCP deploy
    version="1.0.0",
    capabilities=AgentCapabilities(
        streaming=True,
        push_notifications=False,
    ),
    skills=[
        AgentSkill(
            id="detect-text",
            name="Text AI Detection",
            description="Detects AI-generated text using SEA-LION GUARD + Gemini.",
            input_modes=["text/plain"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="detect-image",
            name="Image Manipulation Detection",
            description="Detects deepfakes, GAN artifacts, compositing via Gemini Vision.",
            input_modes=["image/jpeg", "image/png", "image/webp"],
            output_modes=["application/json"],
        ),
        AgentSkill(
            id="detect-audio",
            name="Audio AI Detection",
            description="Transcribes audio via Deepgram and analyses for AI generation.",
            input_modes=["audio/ogg", "audio/mp4", "audio/wav"],
            output_modes=["application/json", "audio/ogg"],
        ),
    ],
)
```

---

## Step 3 — Implement the A2A Task Handler

Create `a2a_handler.py`. This is the bridge between an incoming A2A Task and
SENTINEL's existing detection pipeline.

```python
# a2a_handler.py
import asyncio
import logging
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Task, TaskState, Message, Part,
    TextPart, FilePart, DataPart,
)
from pipeline import detector, translator, formatter, logger
from config import CLICKHOUSE_DB  # import what you need


class SentinelAgentExecutor(AgentExecutor):
    """
    Bridges A2A Task requests into SENTINEL's detection pipeline.
    Implements the AgentExecutor interface required by the A2A SDK.
    """

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Called by the A2A server for each incoming task.
        Runs detection and streams results back via event_queue.
        Never raises — all exceptions converted to FAILED task state.
        """
        task = context.current_task
        message = context.message

        try:
            # Extract content from the A2A Message parts
            text_content = ""
            file_bytes = None
            mime_type = "text/plain"

            for part in message.parts:
                if isinstance(part.root, TextPart):
                    text_content += part.root.text
                elif isinstance(part.root, FilePart):
                    file_bytes = part.root.file.bytes
                    mime_type = part.root.file.mime_type or "application/octet-stream"

            # Route to correct detection path
            if file_bytes and mime_type.startswith("image/"):
                result = await _detect_image(file_bytes, text_content)
            elif file_bytes and mime_type.startswith("audio/"):
                result = await _detect_audio(file_bytes, text_content)
            elif text_content:
                result = await _detect_text(text_content)
            else:
                result = {"error": "No content provided", "detected": False}

            # Emit completed task with JSON result
            await event_queue.enqueue_event(
                _build_completion_event(task, result)
            )

        except Exception as e:
            logging.exception(f"[A2A] Task {task.id} failed: {e}")
            await event_queue.enqueue_event(
                _build_failure_event(task, str(e))
            )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("SENTINEL does not support task cancellation")


async def _detect_text(text: str) -> dict:
    source_lang = translator.detect_language(text)
    english = text
    if source_lang != "en":
        english = await translator.translate_to_english(text, source_lang)
    return await detector.run_full_detection(english)


async def _detect_image(image_bytes: bytes, caption: str = "") -> dict:
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(image_bytes)
        tmp_path = f.name
    try:
        return await detector.run_full_detection(caption or "", file_path=tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def _detect_audio(audio_bytes: bytes, context: str = "") -> dict:
    import tempfile, os
    from media import audio
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        transcription = await audio.transcribe_audio(tmp_path)
        transcript = transcription.get("transcript", "")
        return await _detect_text(transcript) if transcript else {"detected": False}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def _build_completion_event(task: Task, result: dict):
    from a2a.types import TaskStatusUpdateEvent, TaskStatus, Message, Part, DataPart
    import json
    return TaskStatusUpdateEvent(
        task_id=task.id,
        context_id=task.context_id,
        status=TaskStatus(
            state=TaskState.completed,
            message=Message(
                role="agent",
                parts=[Part(root=DataPart(data=result))],
            ),
        ),
        final=True,
    )


def _build_failure_event(task: Task, error_msg: str):
    from a2a.types import TaskStatusUpdateEvent, TaskStatus
    return TaskStatusUpdateEvent(
        task_id=task.id,
        context_id=task.context_id,
        status=TaskStatus(state=TaskState.failed),
        final=True,
    )
```

---

## Step 4 — Mount the A2A Server

Add to `telegram_bot.py` (or create `app.py` as the Cloud Run entrypoint):

```python
# At the bottom of telegram_bot.py or in a separate app.py
import threading
import uvicorn
from a2a.server.apps import A2AStarlette
from a2a.server.request_handlers import DefaultRequestHandler
from a2a_card import SENTINEL_AGENT_CARD
from a2a_handler import SentinelAgentExecutor

def start_a2a_server():
    """Run A2A HTTP server in a background thread alongside Telegram polling."""
    handler = DefaultRequestHandler(
        agent_executor=SentinelAgentExecutor(),
        task_store=None,  # in-memory; use Redis for persistence
    )
    app = A2AStarlette(
        agent_card=SENTINEL_AGENT_CARD,
        http_handler=handler,
    )
    # Cloud Run sets PORT env var; default 8080
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

# Start A2A server in background when bot starts
a2a_thread = threading.Thread(target=start_a2a_server, daemon=True)
a2a_thread.start()
```

---

## Step 5 — Expose AgentCard endpoint

The A2AStarlette app automatically serves:
- `GET /.well-known/agent-card.json` → SENTINEL's AgentCard
- `POST /a2a` → task submission endpoint

Verify after deploy:
```bash
curl https://your-cloud-run-url/.well-known/agent-card.json | python -m json.tool
```

---

## Step 6 — Wire into Telegram `/a2a` command (optional)

Add a Telegram command so users can trigger SENTINEL via A2A for testing:

```python
async def a2a_status(update, context):
    """Show A2A agent card info."""
    card = SENTINEL_AGENT_CARD
    msg = (
        f"<b>SENTINEL A2A Agent</b>\n"
        f"Version: {card.version}\n"
        f"Skills: {len(card.skills)}\n"
        f"Endpoint: {card.url}\n"
    )
    await update.message.reply_text(msg, parse_mode="HTML")
```

---

## Audit checklist

Run these checks against the current codebase:

```
[ ] a2a-sdk installed and importable
[ ] a2a_card.py exists with correct Cloud Run URL
[ ] a2a_handler.py exists — SentinelAgentExecutor implements AgentExecutor
[ ] A2A server starts alongside Telegram polling (background thread or separate process)
[ ] /.well-known/agent-card.json returns valid JSON after deploy
[ ] POST /a2a with a text task returns a completed task with detection result
[ ] All temp files deleted in finally blocks in _detect_image and _detect_audio
[ ] a2a_handler.execute() never raises — converts all exceptions to FAILED state
[ ] tests/test_a2a.py exists with mocked AgentExecutor tests
```

---

## Task states reference

| State | When used |
|---|---|
| `submitted` | Task received, not yet started |
| `working` | Detection pipeline running |
| `completed` | Detection result returned |
| `failed` | Exception in pipeline |
| `input_required` | Need more info from caller |
| `canceled` | Explicitly canceled |

---

## Arguments

$ARGUMENTS

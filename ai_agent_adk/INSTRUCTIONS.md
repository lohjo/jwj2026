# instructions.md — Context Engineering Guide
## Multimodal AI-Generated Content Detection Agent

---

## 1. Project Overview

This project is a **multimodal agentic AI system** that detects AI-generated content across text, image, audio, and video. It serves users across Singapore's multilingual landscape (English, Mandarin, Malay, Tamil, Singlish) via a Telegram Bot frontend and a Google ADK multi-agent backend.

### Core Objectives

| Objective | Description |
|---|---|
| **Clarify content** | Explain what the submitted content is and what was detected |
| **Explain why** | Surface reasoning behind detection verdicts, not just scores |
| **Surface useful context** | Provide background, sources, and related information |
| **Work across Singapore's languages** | Support EN, ZH, MS, TA, and Singlish inputs/outputs |
| **Reduce harm without over-censoring** | Flag harmful AI-generated content while preserving legitimate use |

---

## 2. Tech Stack

| Service | Role | Notes |
|---|---|---|
| **Google ADK** | Multi-agent orchestration framework | Manages agent routing, tool-calling, session state |
| **SEA-LION GUARD** | AI-content detection | SEA-LION API — binary/score detection |
| **SEA-LION v3-70B-IT** | Insights & explanation | SEA-LION API — multilingual reasoning |
| **Gemini 2.5 Flash** | Image + video visual analysis | Used for image captioning, OCR, and frame description via `google-genai` |
| **Deepgram** | Speech-to-text (STT) | Transcribes audio messages and video audio tracks |
| **ElevenLabs** | Text-to-speech (TTS) | Generates voice note replies for audio input users |
| **Telegram Bot API** | Frontend — multimodal input | Accepts text, image, audio, video, voice notes |
| **ClickHouse** | Real-time analytics & logging | Stores detection events, model outputs, user sessions |
| **SearXNG** | Web search for contextual grounding | Self-hosted meta-search engine |

---

## 3. Project Structure

```
AI-Fake-Detector/
├── ai-agent-adk/
│   ├── __init__.py           # Exposes root_agent for ADK
│   ├── agent.py              # Root orchestrator agent
│   ├── tools.py              # Custom tools (SEA-LION API, ClickHouse, SearXNG, media processing)
│   ├── translator.py         # Subagent: multilingual translation (SEA-LION Gemma 9B-IT)
│   ├── chat-cli.py           # CLI runner for local testing
│   ├── INSTRUCTIONS.md       # This file — context engineering guide
│   ├── INTEGRATION.md        # Translation <> Detection integration spec
│   ├── memory.md             # SEA-LION tool calling best practices
│   ├── fix.md                # Telegram bot error fixes log
│   └── .env                  # API keys and environment config
├── telegram_bot.py           # Telegram bot — multimodal handlers
├── image_detector.py         # Gemini-based text/image analysis (legacy)
├── video_detector.py         # OpenCV-based frame analysis (legacy)
├── ocr.py                    # Video frame extraction + OCR analysis
├── config.py                 # Gemini config + frame extraction utility
├── app.py                    # FastAPI REST API
├── detect_cli.py             # CLI text detection
├── requirements.txt          # Python dependencies
├── tests/                    # Unit tests directory
│   ├── __init__.py
│   ├── test_tools.py
│   ├── test_telegram_bot.py
│   ├── test_message_format.py
│   └── test_media_handlers.py
└── README.md
```

---

## 4. Environment Setup

Create a `.env` file in the project root:

```env
# ── SEA-LION API (via OpenAI-compatible endpoint) ──
OPENAI_API_KEY=your-sea-lion-api-key-here
OPENAI_API_BASE=https://api.sea-lion.ai/v1
MODEL=aisingapore/Llama-SEA-LION-v3-70B-IT
GUARD_MODEL=aisingapore/SEA-LION-GUARD

# ── Google Gemini (image/video visual analysis) ──
GEMINI_API_KEY=your-gemini-api-key-here
MODEL_NAME=gemini-2.5-flash

# ── Google ADK ──
GOOGLE_GENAI_USE_VERTEXAI=FALSE

# ── Telegram Bot ──
TELEGRAM_TOKEN=your-telegram-bot-token-here

# ── Deepgram (Speech-to-Text) ──
DEEPGRAM_API_KEY=your-deepgram-api-key-here

# ── ElevenLabs (Text-to-Speech) ──
ELEVENLABS_API_KEY=your-elevenlabs-api-key-here
ELEVENLABS_VOICE_ID=your-voice-id-here

# ── ClickHouse ──
CLICKHOUSE_HOST=your-clickhouse-host
CLICKHOUSE_PORT=8123
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=your-password
CLICKHOUSE_DB=agent_logs

# ── SearXNG ──
SEARXNG_URL=https://your-searxng-instance-url-here
```

### New Dependencies (add to `requirements.txt`)

```
python-telegram-bot==22.6
fastapi
uvicorn
Pillow
google-genai
google-adk
python-dotenv
langdetect
httpx
deepgram-sdk>=3.0.0
elevenlabs>=1.0.0
opencv-python-headless
imagehash
pydub
```

---

## 5. Agent Architecture

### Full Pipeline (Multimodal)

```
[Telegram User Input]
   │
   ├── text ─────────────────────────────────────────────────┐
   ├── image (photo) ──► Gemini captioning + OCR ──────────┐ │
   ├── audio (voice) ──► Deepgram STT ─────────────────────┤ │
   ├── video ──────────► Frame sampling + Gemini caption ──┤ │
   │                     + audio track ► Deepgram STT ─────┘ │
   │                                                          │
   ▼                                                          ▼
[Language Detection]  ←── detect_language(text) → ISO code
   │
   +── If non-English ──► [Translator Subagent]
   │                       SEA-LION Gemma 9B-IT
   │                       → normalised English text
   │
   ▼
[SEA-LION GUARD]  ←── always receives English text
   │
   ├── Returns: {is_ai_generated, confidence, label}
   │
   ▼
[Gemini Insights]  ←── generates structured explanation
   │                    (uses Gemini 2.5 Flash for rich analysis)
   │
   ▼
[Translator Subagent]  ←── translate verdict → user's language
   │
   ▼
[Format Response]  ←── apply message template (§14)
   │
   ▼
[ClickHouse Logger]  ←── log event asynchronously
   │
   ▼
[Telegram Bot Response]
   ├── Text reply (formatted with emoji)
   └── Voice note reply (if input was audio) ←── ElevenLabs TTS
```

---

## 6. Core Agent Files

### `agent.py` — Root Orchestrator

```python
import os
import sys
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool
from .tools import searxng_search
from .translator import root_agent as translator

load_dotenv()

SYSTEM_INSTRUCTION = """
You are a multimodal AI-generated content detection assistant designed for users in Singapore.

Your responsibilities:
1. Receive user-submitted content (text, image caption, audio transcript, video description).
2. Use `searxng_search` to surface relevant context or background if needed.
3. Use `translator` to handle or respond in the user's language (EN, ZH, MS, TA, Singlish).

Tone and behaviour:
- Be factual, neutral, and non-alarmist.
- Always explain WHY content may be AI-generated, not just the verdict.
- Never over-censor. If confidence is low, say so clearly.
- Respond in the same language the user used.
- Provide source links when using web search results.

Translation-Detection Integration Rules:
1. Before calling run_guard_detection, always call detect_language on the input text.
2. If the detected language is not English, call translate_to_english first.
   Pass the translated English text to run_guard_detection and run_insights.
3. After receiving the verdict and explanation from run_insights, call
   translate_from_english to return the response in the user's original language.
4. For OCR output from images, always run detect_language on the extracted text
   before passing to run_guard_detection.
5. For video frame descriptions, treat them as English (generated internally) —
   no pre-translation needed. Translate only the final user-facing response.
6. Never pass non-English text directly to run_guard_detection.
"""

try:
    root_agent = Agent(
        name="root_agent",
        model=LiteLlm(
            model=f"openai/{os.getenv('MODEL', 'aisingapore/Llama-SEA-LION-v3-70B-IT')}"
        ),
        description="Agent to answer questions using search and translation tools.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[searxng_search, AgentTool(agent=translator)],
    )
except Exception as e:
    print(f"Failed to initialise root agent: {e}")
    sys.exit(1)
```

---

### `tools.py` — Custom Tools

See existing `tools.py` for the current implementation. The following new tools must be added:

#### New tool functions to implement:

```python
# ── Image Analysis (Gemini) ───────────────────────────────────────────────────

async def analyse_image_with_gemini(image_path: str) -> Dict[str, Any]:
    """
    Use Gemini 2.5 Flash to analyse an image for AI-generation signals.

    Pipeline:
    1. Load image from disk
    2. Send to Gemini with a structured prompt asking for:
       - Image description / caption
       - OCR text extraction (if any text is visible)
       - AI-generation signal analysis (artifacts, symmetry, texture anomalies)
    3. Return structured dict

    Args:
        image_path: Path to the image file on disk.

    Returns:
        Dictionary with keys:
        - caption (str): Description of the image content
        - ocr_text (str | None): Any text extracted from the image
        - ai_signals (str): Analysis of potential AI-generation indicators
        - raw_response (str): Full Gemini response text
    """
    import google.genai as genai
    from PIL import Image

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return {"error": "GEMINI_API_KEY not set", "caption": "", "ocr_text": None, "ai_signals": ""}

    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(os.getenv("MODEL_NAME", "gemini-2.5-flash"))

        img = Image.open(image_path)

        prompt = """Analyse this image in detail:

1. **Description**: Describe what is shown in the image (1-2 sentences).
2. **Text extraction**: If there is any visible text in the image, extract it exactly as written.
   If no text, write "No text detected".
3. **AI-generation signals**: Look for signs that this image may be AI-generated:
   - Unnatural textures, lighting, or shadows
   - Warped or inconsistent geometry (extra fingers, asymmetric features)
   - Repeating patterns, tiling artifacts
   - Overly smooth skin or surfaces
   - Inconsistent reflections or perspective
   - Watermarks from known AI generators
   If no AI signals are found, say so.

Respond in this exact format:
DESCRIPTION: <your description>
OCR_TEXT: <extracted text or "No text detected">
AI_SIGNALS: <your analysis>"""

        response = model.generate_content([prompt, img])
        text = response.text if hasattr(response, 'text') else str(response)

        # Parse structured response
        caption = ""
        ocr_text = None
        ai_signals = ""

        for line in text.split('\n'):
            if line.startswith("DESCRIPTION:"):
                caption = line.replace("DESCRIPTION:", "").strip()
            elif line.startswith("OCR_TEXT:"):
                raw = line.replace("OCR_TEXT:", "").strip()
                ocr_text = None if raw.lower() == "no text detected" else raw
            elif line.startswith("AI_SIGNALS:"):
                ai_signals = line.replace("AI_SIGNALS:", "").strip()

        return {
            "caption": caption or text[:200],
            "ocr_text": ocr_text,
            "ai_signals": ai_signals,
            "raw_response": text,
        }
    except Exception as e:
        return {"error": str(e), "caption": "", "ocr_text": None, "ai_signals": ""}


# ── Audio Transcription (Deepgram) ────────────────────────────────────────────

async def transcribe_audio_deepgram(audio_path: str) -> Dict[str, Any]:
    """
    Transcribe audio using Deepgram's Nova-2 model.

    Args:
        audio_path: Path to the audio file (OGG, MP3, WAV, M4A supported).

    Returns:
        Dictionary with keys:
        - transcript (str): The transcribed text
        - confidence (float): Overall transcription confidence (0.0-1.0)
        - language (str): Detected language code
        - duration (float): Audio duration in seconds
        - error (str | None): Error message if transcription failed
    """
    try:
        from deepgram import DeepgramClient, PrerecordedOptions, FileSource

        api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not api_key:
            return {"error": "DEEPGRAM_API_KEY not set", "transcript": "", "confidence": 0.0}

        client = DeepgramClient(api_key)

        with open(audio_path, "rb") as f:
            buffer_data = f.read()

        payload: FileSource = {"buffer": buffer_data}
        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            language="en",        # Auto-detects but defaults to English
            detect_language=True,
            punctuate=True,
        )

        response = await asyncio.to_thread(
            client.listen.rest.v1.transcribe_file, payload, options
        )

        result = response.results
        transcript = result.channels[0].alternatives[0].transcript
        confidence = result.channels[0].alternatives[0].confidence
        detected_lang = result.channels[0].detected_language or "en"
        duration = response.metadata.duration if hasattr(response, 'metadata') else 0.0

        return {
            "transcript": transcript,
            "confidence": confidence,
            "language": detected_lang,
            "duration": duration,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e), "transcript": "", "confidence": 0.0, "language": "en", "duration": 0.0}


# ── Text-to-Speech (ElevenLabs) ───────────────────────────────────────────────

async def synthesise_speech_elevenlabs(text: str, output_path: str) -> Dict[str, Any]:
    """
    Convert text to speech using ElevenLabs API.

    Args:
        text: The text to convert to speech (max 5000 chars).
        output_path: Path to save the generated audio file (MP3).

    Returns:
        Dictionary with keys:
        - success (bool): Whether the audio was generated
        - output_path (str): Path to the generated file
        - error (str | None): Error message if failed
    """
    try:
        from elevenlabs import ElevenLabs

        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default: Rachel
        if not api_key:
            return {"success": False, "output_path": "", "error": "ELEVENLABS_API_KEY not set"}

        # Truncate to API limit
        text = text[:5000]

        client = ElevenLabs(api_key=api_key)
        audio = await asyncio.to_thread(
            client.text_to_speech.convert,
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
        )

        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

        return {"success": True, "output_path": output_path, "error": None}
    except Exception as e:
        return {"success": False, "output_path": "", "error": str(e)}


# ── Video Analysis ────────────────────────────────────────────────────────────

async def analyse_video(video_path: str) -> Dict[str, Any]:
    """
    Analyse a video for AI-generation signals by:
    1. Extracting frames at 1fps (max 5 frames)
    2. Sending key frames to Gemini for visual analysis
    3. Extracting audio track and transcribing via Deepgram
    4. Combining visual + audio analysis

    Args:
        video_path: Path to the video file on disk.

    Returns:
        Dictionary with keys:
        - frame_descriptions (list[str]): Gemini descriptions of sampled frames
        - audio_transcript (str): Deepgram transcript of audio track
        - ai_signals (str): Combined AI-generation signal analysis
        - frames_checked (int): Number of frames analysed
        - error (str | None): Error message if analysis failed
    """
    import tempfile

    try:
        # Step 1: Extract frames
        from config import extract_frames
        frames = await asyncio.to_thread(extract_frames, video_path)
        frames = frames[:5]  # Limit to 5 frames

        # Step 2: Analyse frames with Gemini
        frame_descriptions = []
        combined_ai_signals = []
        for frame_path in frames:
            result = await analyse_image_with_gemini(frame_path)
            frame_descriptions.append(result.get("caption", ""))
            if result.get("ai_signals"):
                combined_ai_signals.append(result["ai_signals"])

        # Step 3: Extract and transcribe audio
        audio_transcript = ""
        try:
            audio_path = tempfile.mktemp(suffix=".wav")
            # Extract audio track using ffmpeg (or pydub)
            from pydub import AudioSegment
            audio = await asyncio.to_thread(AudioSegment.from_file, video_path)
            await asyncio.to_thread(audio.export, audio_path, format="wav")
            transcript_result = await transcribe_audio_deepgram(audio_path)
            audio_transcript = transcript_result.get("transcript", "")
            # Clean up
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            audio_transcript = "(Audio extraction failed)"

        # Step 4: Clean up frame files
        for frame_path in frames:
            if os.path.exists(frame_path):
                os.remove(frame_path)

        return {
            "frame_descriptions": frame_descriptions,
            "audio_transcript": audio_transcript,
            "ai_signals": " | ".join(combined_ai_signals) if combined_ai_signals else "No strong AI signals detected in frames",
            "frames_checked": len(frames),
            "error": None,
        }
    except Exception as e:
        return {
            "frame_descriptions": [],
            "audio_transcript": "",
            "ai_signals": "",
            "frames_checked": 0,
            "error": str(e),
        }
```

---

### `translator.py` — Multilingual Subagent

```python
import os
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

load_dotenv()

TRANSLATOR_PROMPT = """You are a translation engine optimised for Singapore's multilingual context.

Your sole purpose is to translate text. You do not have any tools or additional capabilities.

Supported languages: English, Mandarin Chinese (Simplified), Malay, Tamil, Singlish.

Rules:
- Translate the input text provided to the target language instructed to you.
- If the target language is not specified or unclear, default to English.
- Preserve technical terms (e.g. "AI-generated", "deepfake") in English within translations.
- Output ONLY the translated text. Do not include any additional explanations, notes,
  formatting, or any other text besides the translated content.

Detection Context Rules:
- When translating content FOR detection (non-English → English):
  preserve all original phrasing, formatting, and punctuation exactly.
  Do not clean up grammar or fix errors — the detector needs authentic signals.

- When translating verdicts FOR users (English → user language):
  translate naturally and clearly. Rephrase for cultural clarity where needed.
  Always preserve these English terms untranslated: "AI-generated", "deepfake",
  "confidence score", "GUARD", "OCR".

- For Singlish: translate to standard Singapore English, not British or American English.
"""

root_agent = LlmAgent(
    name="translator_agent",
    model=LiteLlm(
        model=f"openai/{os.getenv('MODEL', 'aisingapore/Gemma-SEA-LION-v3-9B-IT')}"
    ),
    description="Translates content across Singapore's languages: EN, ZH, MS, TA, Singlish.",
    instruction=TRANSLATOR_PROMPT,
    tools=[],
)
```

---

## 7. Telegram Bot Integration — Multimodal Handlers

The Telegram Bot acts as the multimodal frontend. All four content types must be handled.

### Handler Registration (in `telegram_bot.py` → `start_bot()`)

```python
from telegram.ext import MessageHandler, filters

app.add_handler(CommandHandler("hello", hello))
app.add_handler(CommandHandler("start", start_command))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(CommandHandler("detect", detect_command))
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
```

### CHANGE 1: `handle_photo` — Image Detection via Telegram

```python
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle photo uploads: download → Gemini analysis → GUARD detection → formatted response.

    Pipeline:
    1. Download the highest-resolution photo from Telegram
    2. Run Gemini visual analysis (caption + OCR + AI signals)
    3. If OCR text found, detect language and translate to English if needed
    4. Combine caption + OCR text + AI signals into a single analysis string
    5. Run SEA-LION GUARD on the combined English text
    6. Run Gemini insights for explanation
    7. Translate response back to user's language
    8. Send formatted response using §14 message template
    """
    if not update.message or not update.message.photo:
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🔍 Analysing image, please wait...")

    session_id = await get_or_create_session(user_id)

    try:
        # Step 1: Download photo (highest resolution = last in list)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        os.makedirs("downloads", exist_ok=True)
        image_path = f"downloads/{photo.file_id}.jpg"
        await file.download_to_drive(image_path)

        # Step 2: Gemini visual analysis
        gemini_result = await analyse_image_with_gemini(image_path)

        # Step 3: Language detection on OCR text
        combined_text = gemini_result.get("caption", "")
        ocr_text = gemini_result.get("ocr_text")
        source_lang = "en"

        if ocr_text and len(ocr_text) >= 20:
            source_lang = detect_language(ocr_text)
            if source_lang != "en" and translate_to_english is not None:
                runner = get_runner()
                if runner:
                    ocr_text = await translate_to_english(ocr_text, source_lang, runner, user_id, session_id)

        # Step 4: Combine for GUARD
        guard_input = f"Image description: {combined_text}"
        if ocr_text:
            guard_input += f"\nExtracted text: {ocr_text}"
        ai_signals = gemini_result.get("ai_signals", "")
        if ai_signals:
            guard_input += f"\nVisual AI signals: {ai_signals}"

        # Step 5: GUARD detection
        detection_result = await run_guard_detection(guard_input, content_type="image_caption", source_lang="en")

        # Step 6: Gemini insights
        insights_result = await run_insights(guard_input, detection_result) if run_insights else None

        # Step 7: Format and translate response
        explanation = (insights_result or {}).get("explanation", "Analysis unavailable.")
        verdict = detection_result.get("label", "Unknown")

        # Build formatted message (§14)
        response = format_detection_response(
            content_type="image",
            verdict=verdict,
            is_ai_generated=detection_result.get("is_ai_generated"),
            confidence=detection_result.get("confidence"),
            explanation=explanation,
            caption=combined_text,
            ocr_text=gemini_result.get("ocr_text"),
            ai_signals=ai_signals,
        )

        # Translate if non-English user
        if source_lang != "en" and translate_from_english is not None:
            runner = get_runner()
            if runner:
                response = await translate_from_english(response, source_lang, runner, user_id, session_id)

        await update.message.reply_text(response, parse_mode="Markdown")

        # Log
        if log_to_clickhouse:
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse, user_id, "image", combined_text[:200],
                verdict, detection_result.get("confidence"), explanation
            ))

        # Cleanup
        if os.path.exists(image_path):
            os.remove(image_path)

    except Exception as e:
        logging.exception("Error in handle_photo")
        await update.message.reply_text(f"❌ Image analysis failed: {e}")
```

### CHANGE 2: `handle_audio` — Audio Detection via Deepgram + ElevenLabs TTS

```python
async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle audio/voice uploads: download → Deepgram STT → GUARD detection → TTS response.

    Pipeline:
    1. Download audio file from Telegram (voice note or audio file)
    2. Transcribe using Deepgram Nova-2
    3. Detect language of transcript
    4. Translate to English if needed
    5. Run SEA-LION GUARD on English transcript
    6. Run insights for explanation
    7. Translate response back to user's language
    8. Send text response + voice note reply (ElevenLabs TTS)
    """
    if not update.message:
        return

    audio = update.message.voice or update.message.audio
    if not audio:
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🎤 Transcribing audio, please wait...")

    session_id = await get_or_create_session(user_id)

    try:
        # Step 1: Download audio
        file = await context.bot.get_file(audio.file_id)
        os.makedirs("downloads", exist_ok=True)
        ext = ".ogg" if update.message.voice else ".mp3"
        audio_path = f"downloads/{audio.file_id}{ext}"
        await file.download_to_drive(audio_path)

        # Step 2: Transcribe with Deepgram
        transcript_result = await transcribe_audio_deepgram(audio_path)
        transcript = transcript_result.get("transcript", "")

        if not transcript:
            await update.message.reply_text("⚠️ Could not transcribe audio. Please try sending a clearer recording.")
            return

        # Step 3: Detect language
        source_lang = transcript_result.get("language", "en")
        if len(transcript) >= 20:
            source_lang = detect_language(transcript) or source_lang

        # Step 4: Translate to English
        english_text = transcript
        if source_lang != "en" and translate_to_english is not None:
            runner = get_runner()
            if runner:
                english_text = await translate_to_english(transcript, source_lang, runner, user_id, session_id)

        # Step 5: GUARD detection
        detection_result = await run_guard_detection(english_text, content_type="audio_transcript", source_lang=source_lang)

        # Step 6: Insights
        insights_result = await run_insights(english_text, detection_result) if run_insights else None

        # Step 7: Format response
        explanation = (insights_result or {}).get("explanation", "Analysis unavailable.")
        verdict = detection_result.get("label", "Unknown")

        response = format_detection_response(
            content_type="audio",
            verdict=verdict,
            is_ai_generated=detection_result.get("is_ai_generated"),
            confidence=detection_result.get("confidence"),
            explanation=explanation,
            transcript=transcript,
        )

        # Translate back
        if source_lang != "en" and translate_from_english is not None:
            runner = get_runner()
            if runner:
                response = await translate_from_english(response, source_lang, runner, user_id, session_id)

        await update.message.reply_text(response, parse_mode="Markdown")

        # Step 8: Optional TTS voice reply
        try:
            tts_path = f"downloads/tts_{audio.file_id}.mp3"
            tts_result = await synthesise_speech_elevenlabs(response[:1000], tts_path)
            if tts_result.get("success"):
                with open(tts_path, "rb") as voice_file:
                    await update.message.reply_voice(voice=voice_file)
                os.remove(tts_path)
        except Exception:
            logging.info("TTS reply skipped — ElevenLabs not available or failed")

        # Log
        if log_to_clickhouse:
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse, user_id, "audio", transcript[:200],
                verdict, detection_result.get("confidence"), explanation
            ))

        # Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        logging.exception("Error in handle_audio")
        await update.message.reply_text(f"❌ Audio analysis failed: {e}")
```

### CHANGE 3: `handle_video` — Video Detection (Frames + Audio)

```python
async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle video uploads: download → frame analysis + audio STT → GUARD → response.

    Pipeline:
    1. Download video from Telegram
    2. Run analyse_video() — extracts frames + audio
    3. Combine frame descriptions + audio transcript
    4. Detect language, translate if needed
    5. Run GUARD + insights
    6. Send formatted response
    """
    if not update.message:
        return

    video = update.message.video or update.message.video_note
    if not video:
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
    except Exception:
        pass

    await update.message.reply_text("🎬 Analysing video, please wait... This may take a moment.")

    session_id = await get_or_create_session(user_id)

    try:
        # Step 1: Download
        file = await context.bot.get_file(video.file_id)
        os.makedirs("downloads", exist_ok=True)
        video_path = f"downloads/{video.file_id}.mp4"
        await file.download_to_drive(video_path)

        # Step 2: Analyse video (frames + audio)
        video_result = await analyse_video(video_path)

        if video_result.get("error") and not video_result.get("frame_descriptions"):
            await update.message.reply_text(f"⚠️ Video analysis failed: {video_result['error']}")
            return

        # Step 3: Combine analysis
        frame_text = " | ".join(video_result.get("frame_descriptions", []))
        audio_text = video_result.get("audio_transcript", "")
        ai_signals = video_result.get("ai_signals", "")

        guard_input = f"Video frame descriptions: {frame_text}"
        if audio_text:
            guard_input += f"\nAudio transcript: {audio_text}"
        if ai_signals:
            guard_input += f"\nVisual AI signals: {ai_signals}"

        # Step 4: Language detection on audio transcript
        source_lang = "en"
        if audio_text and len(audio_text) >= 20:
            source_lang = detect_language(audio_text)
            if source_lang != "en" and translate_to_english is not None:
                runner = get_runner()
                if runner:
                    audio_text_en = await translate_to_english(audio_text, source_lang, runner, user_id, session_id)
                    guard_input = guard_input.replace(audio_text, audio_text_en)

        # Step 5: GUARD detection
        detection_result = await run_guard_detection(guard_input, content_type="video_transcript", source_lang="en")

        # Step 6: Insights
        insights_result = await run_insights(guard_input, detection_result) if run_insights else None
        explanation = (insights_result or {}).get("explanation", "Analysis unavailable.")
        verdict = detection_result.get("label", "Unknown")

        # Step 7: Format response
        response = format_detection_response(
            content_type="video",
            verdict=verdict,
            is_ai_generated=detection_result.get("is_ai_generated"),
            confidence=detection_result.get("confidence"),
            explanation=explanation,
            frames_checked=video_result.get("frames_checked", 0),
            transcript=audio_text,
            ai_signals=ai_signals,
        )

        if source_lang != "en" and translate_from_english is not None:
            runner = get_runner()
            if runner:
                response = await translate_from_english(response, source_lang, runner, user_id, session_id)

        await update.message.reply_text(response, parse_mode="Markdown")

        # Log
        if log_to_clickhouse:
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse, user_id, "video", frame_text[:200],
                verdict, detection_result.get("confidence"), explanation
            ))

        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)

    except Exception as e:
        logging.exception("Error in handle_video")
        await update.message.reply_text(f"❌ Video analysis failed: {e}")
```

### CHANGE 4: `handle_text` — Updated Text Handler with SEA-LION GUARD + Translation + New Format

The existing `handle_text` handler already implements the GUARD + translation pipeline.
Update it to use the new `format_detection_response()` function (§14) instead of raw text output.

Replace the response construction section with:

```python
# After getting detection_result and insights_result:
response = format_detection_response(
    content_type="text",
    verdict=detection_result.get("label", "Unknown"),
    is_ai_generated=detection_result.get("is_ai_generated"),
    confidence=detection_result.get("confidence"),
    explanation=(insights_result or {}).get("explanation", ""),
)
```

---

## 8. ClickHouse Schema

```sql
CREATE TABLE detection_events (
    event_id        UUID DEFAULT generateUUIDv4(),
    timestamp       DateTime DEFAULT now(),
    user_id         String,
    content_type    Enum('text', 'image', 'audio', 'video'),
    content_preview String,
    detection_label String,
    confidence      Nullable(Float32),
    explanation     String
) ENGINE = MergeTree()
ORDER BY (timestamp, user_id);
```

---

## 9. MCP Subagent — Web Crawl & Context

MCP subagents use `.md` context files to ground responses. Structure your context files as:

```
ai-agent-adk/
└── context/
    ├── ai_detection_signals.md     # Known signals of AI-generated content
    ├── singapore_languages.md      # Notes on Singlish, code-switching patterns
    └── harm_reduction_policy.md    # Guidelines on what to flag vs. not flag
```

The MCP subagent should be called when: GUARD confidence is below threshold (< 0.7), the user requests more context or sources, or content touches sensitive topics requiring grounded evidence.

---

## 10. Model Selection Guide

| Task | Model | Reason |
|---|---|---|
| AI-content detection | `aisingapore/SEA-LION-GUARD` | Specialised safety/detection model |
| Orchestration & reasoning | `aisingapore/Llama-SEA-LION-v3-70B-IT` | Complex multilingual reasoning |
| Translation subagent | `aisingapore/Gemma-SEA-LION-v3-9B-IT` | Lightweight, fast, single-purpose |
| Image/video visual analysis | `gemini-2.5-flash` | Multimodal vision, fast, cost-effective |
| Insights generation | `gemini-2.5-flash` | Rich structured explanation with vision context |
| Speech-to-text | `deepgram/nova-2` | Fast, accurate, multilingual STT |
| Text-to-speech | `elevenlabs/eleven_multilingual_v2` | Natural-sounding, multilingual TTS |

### Detection Flow — Which Model Does What

```
User Input ──► [Language Detection: langdetect]
            ──► [Translation: SEA-LION Gemma 9B-IT]
            ──► [GUARD Detection: SEA-LION GUARD]        ← binary verdict
            ──► [Insight Generation: Gemini 2.5 Flash]   ← rich explanation
            ──► [Translation Back: SEA-LION Gemma 9B-IT] ← user's language
```

**Key design decision**: Use **Gemini** (not SEA-LION 70B) for insight generation because:
1. Gemini handles multimodal context (image descriptions, frame analysis) natively
2. Gemini produces more structured, formatted output suitable for the message template
3. SEA-LION GUARD remains the authoritative detection model — Gemini only explains

---

## 11. Running the Agent

### Web Interface (Development)
```bash
cd AI-Fake-Detector
adk web
# Access at http://localhost:8000
```

### CLI Interface (Testing)
```bash
cd AI-Fake-Detector
python -m ai-agent-adk.chat-cli
```

### Telegram Bot (Production)
```bash
cd AI-Fake-Detector
python telegram_bot.py
```

### Run Tests
```bash
cd AI-Fake-Detector
python -m pytest tests/ -v
```

---

## 12. Best Practices

- **Confidence thresholds**: Only return definitive verdicts above 0.85 confidence. Below this, surface uncertainty clearly to the user.
- **Avoid over-censoring**: Always show the reasoning. A low-confidence flag should never silently block content.
- **Language detection**: Auto-detect input language before routing to translator. Use `langdetect`. Skip detection on inputs under 20 characters (defaults to English).
- **Session management**: Use `InMemorySessionService` for development; implement persistent ClickHouse-backed sessions for production.
- **Tool docstrings**: Always include parameter types, return format, and example usage — ADK uses these for tool-calling decisions.
- **Error fallbacks**: Every tool must return a structured error dict, never raise uncaught exceptions.
- **File cleanup**: Always delete downloaded media files after processing to prevent disk bloat.
- **Rate limiting**: Enforce cooldown per user (3 seconds minimum) to prevent API abuse.
- **Typing indicators**: Always send `typing` or `upload_video` chat actions before long operations.
- **Background logging**: Schedule ClickHouse logging as background tasks — never block the response.

---

## 13. Troubleshooting

| Issue | Likely Cause | Fix |
|---|---|---|
| Tool not being called | Instruction doesn't mention tool name | Add explicit tool reference in `SYSTEM_INSTRUCTION` |
| LiteLLM connection error | Wrong API base or key | Check `.env` values |
| `GOOGLE_GENAI_USE_VERTEXAI` error | Using SEA-LION API without Vertex | Set `GOOGLE_GENAI_USE_VERTEXAI=FALSE` |
| ClickHouse insert failure | Schema mismatch or connection issue | Check `detection_events` table schema |
| Translation not triggering | Translator not wrapped in `AgentTool` | Ensure `AgentTool(agent=translator)` in tools list |
| Telegram bot not receiving media | Missing file handler or bot permissions | Add `PHOTO`, `VOICE`, `VIDEO` handlers + enable in BotFather |
| `Runner not available` | Runner never initialised | Use `get_runner()` factory — see `fix.md` Fix 1 |
| `401 Unauthorized` from SEA-LION | `.env` not loaded before tools module | Use `override=True` in `load_dotenv()` — see `fix.md` Fix 3 |
| `langdetect` false positives | Short input (<20 chars) | Skip detection, default to English — see `fix.md` Fix 4 |
| Deepgram transcription empty | Audio format not supported or too short | Convert to WAV first; require minimum 1s audio |
| ElevenLabs TTS fails | API key missing or quota exceeded | Check `ELEVENLABS_API_KEY`; skip TTS gracefully |
| Gemini image analysis fails | `GEMINI_API_KEY` not set | Check `.env`; fall back to text-only GUARD analysis |
| Video analysis timeout | Video too long or too large | Limit to 5 frames; set 60s timeout on video handler |

---

## 14. Message Format Specification

### Problem with Current Format

The current output is a raw wall of text:

> **1. Explanation**: This content is highly likely to be human-generated due to its simplicity and specificity. The query "how to say hello in Chinese" is a common, straightforward request... **2. Observed Signals**: - **Linguistic**: The phrase is concise... **3. Recommended Action**: Treat as human-generated...

This is hard to scan, has no visual hierarchy, and doesn't present the verdict clearly.

### New Message Template

All detection responses must use this structured format. Implement as `format_detection_response()` in `tools.py` or `telegram_bot.py`:

```python
def format_detection_response(
    content_type: str,
    verdict: str,
    is_ai_generated: bool | None,
    confidence: float | None,
    explanation: str,
    caption: str = "",
    ocr_text: str | None = None,
    transcript: str = "",
    ai_signals: str = "",
    frames_checked: int = 0,
) -> str:
    """
    Format a detection result into a user-friendly Telegram message.

    Args:
        content_type: One of 'text', 'image', 'audio', 'video'.
        verdict: Raw verdict label from GUARD.
        is_ai_generated: Boolean detection result (True/False/None).
        confidence: Confidence score 0.0-1.0, or None.
        explanation: Plain-language explanation from insights model.
        caption: Image caption (for image content type).
        ocr_text: Extracted text from image OCR (for image content type).
        transcript: Audio/video transcript text.
        ai_signals: Detected AI-generation signals.
        frames_checked: Number of video frames analysed.

    Returns:
        Formatted Markdown string for Telegram.
    """
    # Verdict emoji
    if is_ai_generated is True:
        verdict_emoji = "🔴"
        verdict_label = "Likely AI-Generated"
    elif is_ai_generated is False:
        verdict_emoji = "🟢"
        verdict_label = "Likely Human-Generated"
    else:
        verdict_emoji = "🟡"
        verdict_label = "Inconclusive"

    # Content type header
    type_icons = {"text": "📝", "image": "🖼️", "audio": "🎤", "video": "🎬"}
    type_icon = type_icons.get(content_type, "📄")

    # Confidence bar
    if confidence is not None:
        pct = int(confidence * 100)
        filled = int(confidence * 10)
        bar = "█" * filled + "░" * (10 - filled)
        confidence_line = f"*Confidence*: {bar} {pct}%"
    else:
        confidence_line = "*Confidence*: Not available"

    # Build message
    lines = []
    lines.append(f"{type_icon} *{content_type.upper()} ANALYSIS*")
    lines.append("")
    lines.append(f"{verdict_emoji} *Verdict*: {verdict_label}")
    lines.append(confidence_line)
    lines.append("")

    # Content preview section (varies by type)
    if content_type == "image":
        if caption:
            lines.append(f"🔎 *Image Content*: {caption[:150]}")
        if ocr_text:
            lines.append(f"📖 *Detected Text*: _{ocr_text[:150]}_")
        if ai_signals:
            lines.append(f"⚠️ *Visual Signals*: {ai_signals[:200]}")
        lines.append("")
    elif content_type == "audio":
        if transcript:
            lines.append(f"📝 *Transcript*: _{transcript[:200]}_")
        lines.append("")
    elif content_type == "video":
        if frames_checked:
            lines.append(f"🎞️ *Frames Analysed*: {frames_checked}")
        if transcript:
            lines.append(f"📝 *Audio Transcript*: _{transcript[:150]}_")
        if ai_signals:
            lines.append(f"⚠️ *Visual Signals*: {ai_signals[:200]}")
        lines.append("")

    # Explanation
    lines.append("💡 *Analysis*")
    # Clean and truncate explanation
    clean_explanation = explanation.strip()
    if len(clean_explanation) > 500:
        clean_explanation = clean_explanation[:497] + "..."
    lines.append(clean_explanation)
    lines.append("")

    # Footer
    lines.append("─" * 20)
    lines.append("🤖 _Powered by SEA-LION GUARD + Gemini_")
    lines.append("_This is an automated analysis. Use your own judgement._")

    return "\n".join(lines)
```

### Example Output — Text Detection

```
📝 TEXT ANALYSIS

🟢 Verdict: Likely Human-Generated
Confidence: ████████░░ 82%

💡 Analysis
This message appears to be a genuine user query asking how to say
"hello" in Chinese. The language is conversational and straightforward,
with no patterns typically associated with AI-generated text. The
simplicity and directness strongly suggest human authorship.

────────────────────
🤖 Powered by SEA-LION GUARD + Gemini
This is an automated analysis. Use your own judgement.
```

### Example Output — Image Detection

```
🖼️ IMAGE ANALYSIS

🔴 Verdict: Likely AI-Generated
Confidence: █████████░ 91%

🔎 Image Content: A photorealistic portrait of a woman with flowing hair
📖 Detected Text: No text detected
⚠️ Visual Signals: Overly smooth skin texture, asymmetric earrings, 
   inconsistent light reflections in eyes

💡 Analysis
This image shows several hallmarks of AI generation: the skin has an
unnaturally smooth, airbrushed quality; the earrings are slightly different
in shape; and the light reflections in each eye come from different angles.
These are common artifacts in diffusion model outputs.

────────────────────
🤖 Powered by SEA-LION GUARD + Gemini
This is an automated analysis. Use your own judgement.
```

### Example Output — Audio Detection

```
🎤 AUDIO ANALYSIS

🟡 Verdict: Inconclusive
Confidence: Not available

📝 Transcript: "The government announced a new policy today that will
   affect all citizens starting from next month..."

💡 Analysis
The transcribed content discusses a policy announcement. The GUARD model
could not make a definitive determination from the transcript alone.
The audio quality and speech patterns would need further analysis.
Consider verifying this claim against official government channels.

────────────────────
🤖 Powered by SEA-LION GUARD + Gemini
This is an automated analysis. Use your own judgement.
```

### Example Output — Video Detection

```
🎬 VIDEO ANALYSIS

🔴 Verdict: Likely AI-Generated
Confidence: ████████░░ 87%

🎞️ Frames Analysed: 5
📝 Audio Transcript: "Welcome to this tutorial on machine learning..."
⚠️ Visual Signals: Consistent face geometry issues across frames,
   unnatural lip-sync timing, flickering background elements

💡 Analysis
Multiple frames show consistent indicators of AI generation: the
speaker's face has subtle geometric inconsistencies between frames,
lip movements don't precisely match the audio timing, and background
elements flicker in ways not typical of real video footage.

────────────────────
🤖 Powered by SEA-LION GUARD + Gemini
This is an automated analysis. Use your own judgement.
```

---

## 15. Implementation Checklist

Use this checklist to track progress on the multimodal features:

### Text Detection ✅ (Complete)
- [x] `handle_text` handler registered
- [x] SEA-LION GUARD integration
- [x] `run_insights` for explanation
- [x] Language detection + translation pipeline
- [x] Rate limiting + session reuse
- [x] ClickHouse logging (background)
- [ ] New message format (`format_detection_response`)

### Image Detection 🔲 (To Implement)
- [ ] Add `handle_photo` handler to `telegram_bot.py`
- [ ] Register `MessageHandler(filters.PHOTO, handle_photo)` in `start_bot()`
- [ ] Implement `analyse_image_with_gemini()` in `tools.py`
- [ ] Add `GEMINI_API_KEY` to `.env`
- [ ] OCR text extraction via Gemini prompt
- [ ] Language detection on OCR text + translation
- [ ] GUARD detection on combined caption + OCR
- [ ] New message format with image-specific fields
- [ ] File download + cleanup
- [ ] Unit tests in `tests/test_media_handlers.py`

### Audio Detection 🔲 (To Implement)
- [ ] Add `handle_audio` handler to `telegram_bot.py`
- [ ] Register `MessageHandler(filters.VOICE | filters.AUDIO, handle_audio)` in `start_bot()`
- [ ] Add `deepgram-sdk` to `requirements.txt`
- [ ] Implement `transcribe_audio_deepgram()` in `tools.py`
- [ ] Add `DEEPGRAM_API_KEY` to `.env`
- [ ] Language detection on transcript + translation
- [ ] GUARD detection on English transcript
- [ ] Add `elevenlabs` to `requirements.txt`
- [ ] Implement `synthesise_speech_elevenlabs()` in `tools.py`
- [ ] Add `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` to `.env`
- [ ] TTS voice reply (graceful fallback if ElevenLabs unavailable)
- [ ] New message format with audio-specific fields
- [ ] File download + cleanup
- [ ] Unit tests

### Video Detection 🔲 (To Implement)
- [ ] Add `handle_video` handler to `telegram_bot.py`
- [ ] Register `MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video)` in `start_bot()`
- [ ] Implement `analyse_video()` in `tools.py`
- [ ] Frame extraction using `config.extract_frames()` (max 5 frames)
- [ ] Gemini analysis per frame via `analyse_image_with_gemini()`
- [ ] Audio track extraction via `pydub`
- [ ] Deepgram transcription of audio track
- [ ] Add `pydub` + `opencv-python-headless` to `requirements.txt`
- [ ] Combined frame + audio → GUARD detection
- [ ] New message format with video-specific fields
- [ ] File download + cleanup
- [ ] Unit tests

### Message Format 🔲 (To Implement)
- [ ] Implement `format_detection_response()` function
- [ ] Emoji-based verdict indicator (🔴🟢🟡)
- [ ] Visual confidence bar
- [ ] Content-type-specific sections (caption, OCR, transcript, frames)
- [ ] Footer with attribution + disclaimer
- [ ] Truncation for long content (500 char explanation, 200 char previews)
- [ ] Markdown-safe formatting (escape special characters)
- [ ] Unit tests in `tests/test_message_format.py`

### Translation Layer 🔲 (To Wire Up)
- [ ] Ensure all handlers follow the 7-step pipeline from §7
- [ ] GUARD always receives English text (never raw multilingual)
- [ ] Gemini insights are generated in English
- [ ] Final response translated back to user's detected language
- [ ] Translation failure never blocks detection (fail-safe)

---

## 16. Unit Test Specifications

All tests go in the `tests/` directory. Run with `python -m pytest tests/ -v`.

### `tests/test_message_format.py`

```python
"""Tests for the format_detection_response() function."""

def test_text_format_human_generated():
    """Green verdict for human-generated text."""
    result = format_detection_response(
        content_type="text", verdict="human-generated",
        is_ai_generated=False, confidence=0.82,
        explanation="Simple conversational query.",
    )
    assert "🟢" in result
    assert "Likely Human-Generated" in result
    assert "82%" in result
    assert "TEXT ANALYSIS" in result

def test_text_format_ai_generated():
    """Red verdict for AI-generated text."""
    result = format_detection_response(
        content_type="text", verdict="ai-generated",
        is_ai_generated=True, confidence=0.95,
        explanation="Repetitive structure and generic phrasing.",
    )
    assert "🔴" in result
    assert "Likely AI-Generated" in result

def test_image_format_includes_caption_and_ocr():
    """Image responses include caption and OCR sections."""
    result = format_detection_response(
        content_type="image", verdict="ai-generated",
        is_ai_generated=True, confidence=0.91,
        explanation="Smooth textures and inconsistent geometry.",
        caption="A woman with flowing hair",
        ocr_text="Hello World",
        ai_signals="Overly smooth skin",
    )
    assert "🖼️" in result
    assert "Image Content" in result
    assert "Detected Text" in result
    assert "Visual Signals" in result

def test_audio_format_includes_transcript():
    """Audio responses include transcript section."""
    result = format_detection_response(
        content_type="audio", verdict="inconclusive",
        is_ai_generated=None, confidence=None,
        explanation="Cannot determine from transcript alone.",
        transcript="The government announced...",
    )
    assert "🎤" in result
    assert "Transcript" in result
    assert "Not available" in result  # confidence

def test_video_format_includes_frames_and_transcript():
    """Video responses include frames count and transcript."""
    result = format_detection_response(
        content_type="video", verdict="ai-generated",
        is_ai_generated=True, confidence=0.87,
        explanation="Frame inconsistencies detected.",
        frames_checked=5,
        transcript="Welcome to this tutorial...",
        ai_signals="Lip-sync issues",
    )
    assert "🎬" in result
    assert "Frames Analysed" in result
    assert "5" in result

def test_explanation_truncated_at_500_chars():
    """Long explanations are truncated."""
    long_text = "A" * 1000
    result = format_detection_response(
        content_type="text", verdict="test",
        is_ai_generated=None, confidence=None,
        explanation=long_text,
    )
    assert "..." in result
    assert len(result) < len(long_text) + 200

def test_footer_always_present():
    """Footer with disclaimer is always included."""
    result = format_detection_response(
        content_type="text", verdict="test",
        is_ai_generated=None, confidence=None,
        explanation="Test.",
    )
    assert "SEA-LION GUARD" in result
    assert "automated analysis" in result
```

### `tests/test_media_handlers.py`

```python
"""Tests for media handler tool functions (mocked — no real API calls)."""

import asyncio
from unittest.mock import patch, MagicMock

def test_analyse_image_returns_structured_dict_on_error():
    """Image analysis returns error dict, never raises."""
    with patch.dict('os.environ', {'GEMINI_API_KEY': ''}):
        from tools import analyse_image_with_gemini
        result = asyncio.run(analyse_image_with_gemini("/nonexistent/path.jpg"))
        assert "error" in result
        assert isinstance(result, dict)

def test_transcribe_audio_returns_structured_dict_on_error():
    """Audio transcription returns error dict, never raises."""
    with patch.dict('os.environ', {'DEEPGRAM_API_KEY': ''}):
        from tools import transcribe_audio_deepgram
        result = asyncio.run(transcribe_audio_deepgram("/nonexistent/audio.ogg"))
        assert "error" in result
        assert result["transcript"] == ""

def test_synthesise_speech_returns_structured_dict_on_error():
    """TTS returns error dict, never raises."""
    with patch.dict('os.environ', {'ELEVENLABS_API_KEY': ''}):
        from tools import synthesise_speech_elevenlabs
        result = asyncio.run(synthesise_speech_elevenlabs("Hello", "/tmp/test.mp3"))
        assert result["success"] is False
        assert "error" in result

def test_analyse_video_returns_structured_dict_on_error():
    """Video analysis returns error dict, never raises."""
    from tools import analyse_video
    result = asyncio.run(analyse_video("/nonexistent/video.mp4"))
    assert "error" in result
    assert result["frames_checked"] == 0
```
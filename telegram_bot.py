import os
import sys
import logging
import asyncio
import importlib
import datetime
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters


# Initialize logging early so we can log .env loading and failures
logging.basicConfig(level=logging.INFO)

# Ensure project root is on sys.path so local modules (image_detector, etc.) import
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Load .env early so TELEGRAM_TOKEN (or TELEGRAM_BOT_TOKEN) can be resolved once at import time
# Try several candidate locations (project root, ai_agent_adk package-local, repo root),
# then fall back to find_dotenv() if none found.
project_root = Path(__file__).resolve().parent
candidates = [
    project_root / '.env',
    project_root / 'ai_agent_adk' / '.env',
    project_root.parent / '.env',
]
loaded_env = False
for p in candidates:
    try:
        p_resolved = p.resolve()
    except Exception:
        p_resolved = p
    logging.info(f"Checking .env candidate: {p_resolved} (exists={p_resolved.exists()})")
    if p_resolved.exists():
        load_dotenv(dotenv_path=p_resolved, override=True)
        logging.info(f"Loaded .env from: {p_resolved}")
        loaded_env = True
        break

if not loaded_env:
    # Fallback to find_dotenv() which searches parent directories
    found = find_dotenv()
    if found:
        load_dotenv(dotenv_path=found, override=True)
        logging.info(f"Loaded .env from: {found}")
    else:
        logging.info("No .env file found in candidate locations; relying on environment variables")

# Fail fast if critical API keys are missing to avoid silent 401s from downstream clients
if not os.environ.get("OPENAI_API_KEY"):
    logging.error("OPENAI_API_KEY not found in .env — SEA-LION / OpenAI API calls will fail with 401")
    sys.exit(1)

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")

# Module-level constants resolved once at startup
APP_NAME: str = "content-detection-agent"

# Use the project text detector
try:
    from image_detector import detect_fake_text
except Exception:
    detect_fake_text = None

# Import image manipulation detector
try:
    from image_detector import detect_image_manipulation
except Exception:
    detect_image_manipulation = None

# Import translation and detection utilities
# Handle hyphenated module name using importlib
detect_language = None
translate_to_english = None
translate_from_english = None
run_guard_detection = None
run_insights = None
log_to_clickhouse = None
format_detection_response = None
analyse_image_with_gemini = None
transcribe_audio_deepgram = None
synthesise_speech_elevenlabs = None
analyse_video = None
detect_misinformation = None

try:
    # Try common import forms first (underscore variant)
    # Ensure project root is on sys.path so local `ai_agent_adk` package is importable
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    try:
        tools_module = importlib.import_module('ai_agent_adk.tools')
    except Exception:
        # Fallback: try to load tools.py directly by path to avoid executing
        # package-level side effects in ai_agent_adk.__init__ (which may import agent.py)
        try:
            import importlib.util
            # First try underscore directory (ai_agent_adk)
            pkg_dir = os.path.join(os.path.dirname(__file__), 'ai_agent_adk')
            tools_path = os.path.join(pkg_dir, 'tools.py')
            if not os.path.exists(tools_path):
                # Fallback to hyphenated directory name used by some forks
                pkg_dir = os.path.join(os.path.dirname(__file__), 'ai-agent-adk')
                tools_path = os.path.join(pkg_dir, 'tools.py')

            if os.path.exists(tools_path):
                spec = importlib.util.spec_from_file_location('ai_agent_adk.tools', tools_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                tools_module = module
            else:
                raise ImportError("ai_agent_adk/tools.py not found in expected locations")
        except Exception:
            logging.exception("Failed to load ai_agent_adk.tools via fallback path")
            tools_module = None

    if tools_module:
        detect_language = getattr(tools_module, 'detect_language', None)
        translate_to_english = getattr(tools_module, 'translate_to_english', None)
        translate_from_english = getattr(tools_module, 'translate_from_english', None)
        run_guard_detection = getattr(tools_module, 'run_guard_detection', None)
        run_insights = getattr(tools_module, 'run_insights', None)
        log_to_clickhouse = getattr(tools_module, 'log_to_clickhouse', None)
        format_detection_response = getattr(tools_module, 'format_detection_response', None)
        analyse_image_with_gemini = getattr(tools_module, 'analyse_image_with_gemini', None)
        transcribe_audio_deepgram = getattr(tools_module, 'transcribe_audio_deepgram', None)
        synthesise_speech_elevenlabs = getattr(tools_module, 'synthesise_speech_elevenlabs', None)
        analyse_video = getattr(tools_module, 'analyse_video', None)
        detect_misinformation = getattr(tools_module, 'detect_misinformation', None)
    else:
        logging.warning("Could not import translation/detection utilities from ai-agent-adk.tools")
except Exception:
    logging.exception("Unexpected error while importing translation/detection utilities")


logging.basicConfig(level=logging.INFO)


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass
    await update.message.reply_text(f'Hello {update.effective_user.first_name}')


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to the AI Content Detection Bot!\n\n"
        "Send me any content — text, image, audio, or video — and I'll analyse it "
        "for signs of AI generation.\n\n"
        "Commands:\n"
        "/start — Show this welcome message\n"
        "/help — Show usage instructions\n"
        "/detect <text> — Analyse text directly\n"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *AI Content Detection Bot — Help*\n\n"
        "📝 *Text*: Send any text message to analyse\n"
        "🖼️ *Image*: Send a photo for visual AI-signal analysis\n"
        "🎤 *Audio*: Send a voice note or audio file for transcription + analysis\n"
        "🎬 *Video*: Send a video for frame + audio analysis\n\n"
        "All responses include a verdict, confidence score, and explanation.\n"
        "Supported languages: EN, ZH, MS, TA, Singlish.",
        parse_mode="HTML",
    )


async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Echo command: /echo some text
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    args = context.args if hasattr(context, "args") else []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text("Usage: /echo <some text>")
        return
    await update.message.reply_text(text)


# ── Auto-research helper: triggers when content is flagged ─────────────────────
async def _auto_research_if_flagged(
    content_preview: str,
    detection_result: dict | None,
    misinfo_result: dict | None,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    If detection flags content as AI-generated or unsafe, automatically run
    the research_agent to find corroborating web evidence and save the report
    under research/summaries/.

    Runs as a background task so it doesn't block the user response.
    """
    is_ai = (detection_result or {}).get("is_ai_generated") is True
    is_unsafe = (detection_result or {}).get("safety_flag") == "unsafe"
    is_misinfo = (misinfo_result or {}).get("misinformation_detected") is True

    if not (is_ai or is_unsafe or is_misinfo):
        return  # content is clean — skip

    # Build a research query from the content
    label = (detection_result or {}).get("label", "AI-generated")
    query = f"fact check: {content_preview[:200]}"

    try:
        from research_agent import research as do_research

        result = await do_research(query)

        if result.summary_path:
            from pathlib import Path
            summary_text = Path(result.summary_path).read_text(encoding="utf-8")
            preview = summary_text[:600]
            reason = []
            if is_ai:
                reason.append("AI-generated")
            if is_unsafe:
                reason.append("unsafe")
            if is_misinfo:
                reason.append("misinformation")
            reason_str = ", ".join(reason)

            await update.message.reply_text(
                f"🔎 <b>Auto-Research</b> (flagged as {reason_str})\n\n"
                f"{preview}\n\n"
                f"({len(result.sources)} sources analysed)",
                parse_mode="HTML",
            )
            # Also send the full report as a file
            with open(result.summary_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=Path(result.summary_path).name,
                )
        else:
            logging.info("Auto-research returned no summary for flagged content")
    except Exception:
        logging.exception("Auto-research failed for flagged content")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle plain text messages with multilingual translation and detection pipeline.
    
    Translation-Detection Pipeline:
    1. Extract raw content
    2. Detect language
    3. Translate to English if needed
    4. Run detection on English text
    5. Run insights on English text
    6. Translate response back to user's language
    7. Send response
    """
    if not update.message or not update.message.text:
        return

    # Rate limiting and session reuse helpers are defined below
    raw_text = update.message.text

    user_id = str(update.effective_user.id)

    # FIX 8: rate limiting
    if not await check_rate_limit(user_id, update):
        return

    # FIX 1: typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    # FIX 6: get or create session
    session_id = await get_or_create_session(user_id)
    
    # Step 1: Extract raw content (already done above)
    
    # Step 2: Detect language
    # Guard against unreliable detection on very short strings
    if detect_language is not None and len(raw_text) >= 20:
        try:
            source_lang = detect_language(raw_text)
        except Exception:
            logging.exception("detect_language failed; defaulting to English")
            source_lang = "en"
    else:
        source_lang = "en"
        if detect_language is None:
            logging.warning("detect_language not available, defaulting to English")
        else:
            logging.info("Skipping language detection for short input; defaulting to English")
    
    # Step 3-7: Translation and detection pipeline
    if detect_fake_text is not None:
        await update.message.reply_text("Analyzing text, please wait...")
        try:
            # FIX 2: Translate to English if available (requires runner). If not available, skip.
            english_text = raw_text
            if source_lang != "en" and translate_to_english is not None:
                try:
                    # translate_to_english requires a runner; use module-level runner
                    runner = get_runner()
                    if runner is not None:
                        english_text = await translate_to_english(raw_text, source_lang, runner, user_id, session_id)
                    else:
                        logging.info("Runner not available; skipping translation to English")
                except Exception:
                    logging.exception("translate_to_english failed; using original text")

            # FIX 2: Detection pipeline — GUARD + misinformation concurrently
            detection_result = None
            insights_result = None
            misinfo_result = None

            coros = []
            if run_guard_detection is not None:
                coros.append(run_guard_detection(english_text, source_lang=source_lang))
            else:
                coros.append(asyncio.coroutine(lambda: None)() if False else asyncio.sleep(0))

            if detect_misinformation is not None:
                coros.append(detect_misinformation(english_text, context_description="text message"))
            else:
                coros.append(asyncio.sleep(0))

            gathered = await asyncio.gather(*coros, return_exceptions=True)
            if run_guard_detection is not None and not isinstance(gathered[0], BaseException):
                detection_result = gathered[0]
            if detect_misinformation is not None and not isinstance(gathered[1], BaseException):
                misinfo_result = gathered[1]

            if run_insights is not None:
                insights_result = await run_insights(
                    english_text, detection_result or {},
                    misinformation_result=misinfo_result,
                )

            # FIX 3: Defer logging (background) and translate back concurrently where possible
            if log_to_clickhouse is not None:
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            log_to_clickhouse,
                            {
                                "user_id": user_id,
                                "session_id": session_id,
                                "content_type": "text",
                                "source_language": source_lang,
                                "content_preview": raw_text[:500],
                                "guard_label": (detection_result or {}).get('label', ''),
                                "guard_verdict": "ai_generated" if (detection_result or {}).get('is_ai_generated') else "human_generated" if (detection_result or {}).get('is_ai_generated') is False else "inconclusive",
                                "guard_confidence": (detection_result or {}).get('confidence'),
                                "misinfo_detected": (misinfo_result or {}).get('misinformation_detected', False),
                                "misinfo_type": (misinfo_result or {}).get('misinformation_type', 'none'),
                                "explanation": (insights_result or {}).get('explanation', ''),
                                "is_harmful": (insights_result or {}).get('is_harmful', False),
                            }
                        )
                    )
                except Exception:
                    logging.exception("Failed to schedule clickhouse logging")

            # Translate explanation back if possible (may require runner)
            final_response = None
            explanation = ""
            if insights_result is not None:
                explanation = insights_result.get('explanation', '')

            # Use format_detection_response if available (§14)
            if format_detection_response is not None and detection_result is not None:
                final_response = format_detection_response(
                    content_type="text",
                    verdict=detection_result.get("label", "Unknown"),
                    is_ai_generated=detection_result.get("is_ai_generated"),
                    confidence=detection_result.get("confidence"),
                    explanation=explanation or "",
                )
            elif explanation:
                final_response = explanation
            else:
                # Run legacy detector as fallback
                final_response = str(await asyncio.to_thread(detect_fake_text, english_text))

            # Translate formatted response back if non-English
            if source_lang != "en" and translate_from_english is not None and final_response:
                try:
                    runner = get_runner()
                    if runner is not None:
                        final_response = await translate_from_english(final_response, source_lang, runner, user_id, session_id)
                except Exception:
                    logging.exception("translate_from_english failed; using English response")

            await update.message.reply_text(final_response, parse_mode="HTML")

            # Auto-research if flagged
            asyncio.create_task(
                _auto_research_if_flagged(
                    english_text, detection_result, misinfo_result, update, context
                )
            )
        except Exception as e:
            result = f"Detection error: {e}"
            logging.exception("Error in handle_text pipeline")
            await update.message.reply_text(result)
    else:
        await update.message.reply_text(f"You said: {raw_text}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads: download → Gemini analysis → GUARD detection → formatted response."""
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

        # Step 5: Run GUARD + misinformation + image manipulation concurrently
        coros = [
            run_guard_detection(guard_input, content_type="image_caption", source_lang="en"),
        ]
        if detect_misinformation is not None:
            coros.append(detect_misinformation(guard_input, context_description="image with OCR text"))
        else:
            coros.append(asyncio.sleep(0))
        if detect_image_manipulation is not None:
            coros.append(detect_image_manipulation(image_path))
        else:
            coros.append(asyncio.sleep(0))

        gathered = await asyncio.gather(*coros, return_exceptions=True)
        detection_result = gathered[0] if not isinstance(gathered[0], BaseException) else {}
        misinfo_result = gathered[1] if not isinstance(gathered[1], BaseException) else None
        manip_result = gathered[2] if not isinstance(gathered[2], BaseException) else None

        # Step 6: Gemini insights with all detection results
        insights_result = await run_insights(
            guard_input, detection_result,
            misinformation_result=misinfo_result,
            manipulation_result=manip_result,
        ) if run_insights else None

        # Step 7: Format and translate response
        explanation = (insights_result or {}).get("explanation", "Analysis unavailable.")
        verdict = detection_result.get("label", "Unknown")

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

        await update.message.reply_text(response, parse_mode="HTML")

        # Auto-research if flagged
        asyncio.create_task(
            _auto_research_if_flagged(
                guard_input, detection_result, misinfo_result, update, context
            )
        )

        # Log
        if log_to_clickhouse:
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse,
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "content_type": "image",
                    "content_preview": combined_text[:500],
                    "guard_label": verdict,
                    "guard_verdict": "ai_generated" if detection_result.get('is_ai_generated') else "human_generated" if detection_result.get('is_ai_generated') is False else "inconclusive",
                    "guard_confidence": detection_result.get("confidence"),
                    "misinfo_detected": (misinfo_result or {}).get('misinformation_detected', False),
                    "misinfo_type": (misinfo_result or {}).get('misinformation_type', 'none'),
                    "manipulation_detected": (manip_result or {}).get('manipulation_detected', False),
                    "manipulation_type": (manip_result or {}).get('manipulation_type', 'none'),
                    "explanation": explanation,
                    "is_harmful": (insights_result or {}).get('is_harmful', False),
                }
            ))

        # Cleanup
        if os.path.exists(image_path):
            os.remove(image_path)

    except Exception as e:
        logging.exception("Error in handle_photo")
        await update.message.reply_text(f"❌ Image analysis failed: {e}")


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle audio/voice uploads: download → Deepgram STT → GUARD detection → TTS response."""
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

        await update.message.reply_text(response, parse_mode="HTML")

        # Auto-research if flagged
        asyncio.create_task(
            _auto_research_if_flagged(
                english_text, detection_result, None, update, context
            )
        )

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
                log_to_clickhouse,
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "content_type": "audio",
                    "source_language": source_lang,
                    "content_preview": transcript[:500],
                    "guard_label": verdict,
                    "guard_verdict": "ai_generated" if detection_result.get('is_ai_generated') else "human_generated" if detection_result.get('is_ai_generated') is False else "inconclusive",
                    "guard_confidence": detection_result.get("confidence"),
                    "explanation": explanation,
                    "is_harmful": (insights_result or {}).get('is_harmful', False),
                }
            ))

        # Cleanup
        if os.path.exists(audio_path):
            os.remove(audio_path)

    except Exception as e:
        logging.exception("Error in handle_audio")
        await update.message.reply_text(f"❌ Audio analysis failed: {e}")


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle video uploads: download → frame analysis + audio STT → GUARD → response."""
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

        await update.message.reply_text(response)

        # Auto-research if flagged
        asyncio.create_task(
            _auto_research_if_flagged(
                guard_input, detection_result, None, update, context
            )
        )

        # Log
        if log_to_clickhouse:
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse,
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "content_type": "video",
                    "source_language": source_lang,
                    "content_preview": frame_text[:500],
                    "guard_label": verdict,
                    "guard_verdict": "ai_generated" if detection_result.get('is_ai_generated') else "human_generated" if detection_result.get('is_ai_generated') is False else "inconclusive",
                    "guard_confidence": detection_result.get("confidence"),
                    "explanation": explanation,
                    "is_harmful": (insights_result or {}).get('is_harmful', False),
                }
            ))

        # Cleanup
        if os.path.exists(video_path):
            os.remove(video_path)

    except Exception as e:
        logging.exception("Error in handle_video")
        await update.message.reply_text(f"❌ Video analysis failed: {e}")


async def crawl_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/crawl <query or URLs> — Crawl web pages, detect AI content, save flagged results to .md."""
    args = context.args if hasattr(context, "args") else []
    raw_input = " ".join(args).strip()
    if not raw_input:
        await update.message.reply_text("Usage: /crawl <search query or URLs>")
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🕷️ Crawling and analysing, please wait...")

    try:
        from web_crawler import crawl_and_flag

        # If the input looks like URLs, split them; otherwise treat as search query
        tokens = raw_input.split()
        explicit_urls = [t for t in tokens if t.startswith("http://") or t.startswith("https://")]
        query = " ".join(t for t in tokens if t not in explicit_urls) or raw_input

        report_path = await crawl_and_flag(
            query=query,
            urls=explicit_urls if explicit_urls else None,
        )

        # Read and preview the report
        report_text = report_path.read_text(encoding="utf-8")
        preview = report_text[:800]
        await update.message.reply_text(
            f"📄 <b>Crawl Report</b>\n\n<pre>{preview}</pre>",
            parse_mode="HTML",
        )

        # Send full report as file attachment
        with open(report_path, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename=report_path.name,
            )

        # Log to ClickHouse
        if log_to_clickhouse:
            session_id = await get_or_create_session(user_id)
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse,
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "content_type": "text",
                    "content_preview": f"crawl: {query[:480]}",
                    "guard_verdict": "human_generated",
                    "explanation": f"Web crawl query: {query}",
                }
            ))
    except Exception as exc:
        logging.exception("Error in crawl_command")
        await update.message.reply_text(f"❌ Crawl failed: {exc}")


async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/research <query> — Search the web, summarise, and reply with findings."""
    args = context.args if hasattr(context, "args") else []
    query = " ".join(args).strip()
    if not query:
        await update.message.reply_text("Usage: /research <your question>")
        return

    user_id = str(update.effective_user.id)
    if not await check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🔍 Researching, please wait...")

    try:
        from research_agent import research as do_research

        result = await do_research(query)

        if result.cache_hit and result.skill_path:
            from pathlib import Path
            skill_text = Path(result.skill_path).read_text(encoding="utf-8")
            preview = skill_text[:800]
            await update.message.reply_text(
                f"📚 <b>Cached Skill Card</b>\n\n<pre>{preview}</pre>",
                parse_mode="HTML",
            )
        elif result.summary_path:
            from pathlib import Path
            summary_text = Path(result.summary_path).read_text(encoding="utf-8")
            preview = summary_text[:800]
            await update.message.reply_text(
                f"📝 <b>Research Summary</b>\n\n{preview}\n\n"
                f"({len(result.sources)} sources analysed)",
                parse_mode="HTML",
            )
            # Send full summary as file attachment
            with open(result.summary_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=Path(result.summary_path).name,
                )
        else:
            await update.message.reply_text("⚠️ No results found for your query.")

        # Log research event to ClickHouse
        if log_to_clickhouse:
            session_id = await get_or_create_session(user_id)
            asyncio.create_task(asyncio.to_thread(
                log_to_clickhouse,
                {
                    "user_id": user_id,
                    "session_id": session_id,
                    "content_type": "text",
                    "content_preview": query[:500],
                    "guard_verdict": "human_generated",
                    "explanation": f"Research query: {query}",
                }
            ))
    except Exception as exc:
        logging.exception("Error in research_command")
        await update.message.reply_text(f"❌ Research failed: {exc}")


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /detect <text>
    if detect_fake_text is None:
        await update.message.reply_text("Text detector is not available.")
        return

    # typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    args = context.args if hasattr(context, "args") else []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text("Usage: /detect <text>")
        return
    await update.message.reply_text("Analyzing text, please wait...")
    user_id = str(update.effective_user.id)

    # Rate limit
    if not await check_rate_limit(user_id, update):
        return

    # Reuse session
    session_id = await get_or_create_session(user_id)

    try:
        # Run guard detection (async) if available
        if run_guard_detection is not None:
            detection_result = await run_guard_detection(text)
            insights_result = await run_insights(text, detection_result) if run_insights is not None else None
            # Schedule logging in background
            if log_to_clickhouse is not None:
                asyncio.create_task(asyncio.to_thread(log_to_clickhouse, {
                    "user_id": user_id,
                    "content_type": "text",
                    "content_preview": text[:500],
                    "guard_label": detection_result.get('label', ''),
                    "guard_verdict": "ai_generated" if detection_result.get('is_ai_generated') else "human_generated" if detection_result.get('is_ai_generated') is False else "inconclusive",
                    "guard_confidence": detection_result.get('confidence'),
                    "explanation": (insights_result or {}).get('explanation', ''),
                    "is_harmful": (insights_result or {}).get('is_harmful', False),
                }))
            final = (insights_result or {}).get('explanation') or str(detection_result)
        else:
            final = str(await asyncio.to_thread(detect_fake_text, text))
    except Exception as e:
        final = f"Detection error: {e}"

    await update.message.reply_text(final, parse_mode="HTML")


def get_token() -> str:
    # Accept either TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN (common name in .env)
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("Environment variable TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN is not set.")
        return ""
    return token


# -------------------- Session reuse + rate limiting helpers --------------------
session_service = InMemorySessionService()
user_sessions: dict[str, str] = {}

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
            logging.info("ADK runner initialised successfully")
        except Exception:
            logging.exception("Failed to initialise ADK runner")
    return _runner

async def get_or_create_session(user_id: str) -> str:
    if user_id not in user_sessions:
        session_id = f"session-{user_id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            await session_service.create_session(app_name="ai-fake-detector", user_id=user_id, session_id=session_id, state={})
        except Exception:
            logging.exception("Failed to create session; continuing without persistent session")
        user_sessions[user_id] = session_id
    return user_sessions[user_id]

user_last_request: dict[str, float] = {}
COOLDOWN_SECONDS = 3.0

async def check_rate_limit(user_id: str, update) -> bool:
    now = asyncio.get_event_loop().time()
    last = user_last_request.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        try:
            await update.message.reply_text("Please wait a moment before sending another request.")
        except Exception:
            pass
        return False
    user_last_request[user_id] = now
    return True



def main_cli():
    """Run the text detector from the command line in an interactive loop."""
    if detect_fake_text is None:
        print("Text detector is not available.", file=sys.stderr)
        sys.exit(1)

    # Check for non-interactive use first (text passed as arguments)
    args = [arg for arg in sys.argv[1:] if arg != '--cli']
    if args:
        text = " ".join(args).strip()
        if text:
            try:
                result = detect_fake_text(text)
                print("=== Analysis Result ===")
                print(result)
            except Exception as e:
                print(f"Detection error: {e}", file=sys.stderr)
        else:
            print("No text provided.", file=sys.stderr)
        sys.exit(0)

    # Interactive loop
    print("Entering interactive mode. Type 'quit' or 'exit' to stop.")
    while True:
        try:
            text = input("Enter text to analyze: ").strip()
            if not text:
                continue
            if text.lower() in ('quit', 'exit'):
                print("Exiting interactive mode.")
                break

            try:
                result = detect_fake_text(text)
                print("=== Analysis Result ===")
                print(result)
            except Exception as e:
                print(f"Detection error: {e}", file=sys.stderr)

        except (EOFError, KeyboardInterrupt):
            print("\nExiting interactive mode.")
            break


def start_bot():
    """Initializes and starts the Telegram bot."""
    token = TELEGRAM_TOKEN
    print(f"[DEBUG] Raw token value: '{token}'")  # will show quotes, spaces, newlines
    print(f"[DEBUG] Token length: {len(token)}") 
    if not token:
        logging.error("TELEGRAM_TOKEN not set — cannot start bot")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("hello", hello))
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("detect", detect_command))
    app.add_handler(CommandHandler("research", research_command))
    app.add_handler(CommandHandler("crawl", crawl_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))

    logging.info("Starting Telegram bot polling...")
    app.run_polling()


if __name__ == "__main__":
    if '--cli' in sys.argv:
        main_cli()
    else:
        start_bot()
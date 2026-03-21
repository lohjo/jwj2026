"""
telegram_bot.py — Telegram bot handlers only, no business logic.

All detection logic lives in pipeline/ and media/ modules.
"""

import asyncio
import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Coroutine

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    TELEGRAM_TOKEN,
    COOLDOWN_SECONDS,
    HEALTH_PORT,
    LIVE_API_TIMEOUT_SECONDS,
    TELEGRAM_WEBHOOK_ENABLED,
    TELEGRAM_WEBHOOK_URL,
    TELEGRAM_WEBHOOK_SECRET,
)
from pipeline.translator import detect_language, translate_to_english, translate_from_english
from pipeline.guard import run_guard_detection
from pipeline.detector import detect_misinformation, run_full_detection
from pipeline.insights import call_llm, run_insights
from pipeline.formatter import format_detection_message
from pipeline.logger import log_to_clickhouse

try:
    from media.image import extract_text_from_image, analyse_image_with_gemini, detect_image_manipulation
except Exception:
    extract_text_from_image = None
    analyse_image_with_gemini = None
    detect_image_manipulation = None

try:
    from media.audio import transcribe_audio, synthesise_speech
except Exception:
    transcribe_audio = None
    synthesise_speech = None

try:
    from media import live
except Exception:
    live = None

try:
    from media.video import analyse_video
except Exception:
    analyse_video = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_webhook_app = None
_webhook_app_lock = asyncio.Lock()

# ── Rate limiting ─────────────────────────────────────────────────────
_user_last_request: dict[str, float] = {}


async def _check_rate_limit(user_id: str, update: Update) -> bool:
    now = asyncio.get_event_loop().time()
    last = _user_last_request.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        try:
            await update.message.reply_text(
                "Please wait a moment before sending another request."
            )
        except Exception:
            pass
        return False
    _user_last_request[user_id] = now
    return True


def _verdict_str(detection_result: dict) -> str:
    is_safe = detection_result.get("is_safe")
    if is_safe is True:
        return "safe"
    if is_safe is False:
        return "unsafe"
    return "inconclusive"


def _schedule_log(row: dict) -> None:
    """Fire-and-forget ClickHouse log — never raises."""
    _schedule_background(asyncio.to_thread(log_to_clickhouse, row))


def _schedule_background(coro: Coroutine[Any, Any, Any]) -> None:
    """
    Schedule a background coroutine safely.

    If scheduling fails (or is mocked in tests), close the coroutine to avoid
    un-awaited coroutine warnings.
    """
    try:
        scheduled = asyncio.create_task(coro)
        if not isinstance(scheduled, asyncio.Task):
            coro.close()
    except Exception:
        coro.close()
        logger.debug("Failed to schedule background task", exc_info=True)


# ── Auto-research background task ────────────────────────────────────
async def _auto_research_if_flagged(
    content_preview: str,
    detection_result: dict | None,
    misinfo_result: dict | None,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    source_lang: str = "en",
) -> None:
    is_unsafe = (detection_result or {}).get("is_safe") is False
    is_misinfo = (misinfo_result or {}).get("misinformation_detected") is True

    if not (is_unsafe or is_misinfo):
        return

    try:
        from research_agent.agent import research

        result = await research(f"fact check: {content_preview[:200]}")

        if result.get("summary_path"):
            summary_text = Path(result["summary_path"]).read_text(encoding="utf-8")
            preview = summary_text[:600]
            reasons = []
            if is_unsafe:
                reasons.append("unsafe")
            if is_misinfo:
                reasons.append("misinformation")

            response = (
                f"🔎 <b>Auto-Research</b> (flagged as {', '.join(reasons)})\n\n"
                f"{preview}\n\n"
                f"({len(result.get('sources', []))} sources analysed)"
            )

            if source_lang != "en":
                response = await translate_from_english(response, source_lang)

            await update.message.reply_text(response, parse_mode="HTML")

            with open(result["summary_path"], "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=Path(result["summary_path"]).name,
                )
    except Exception:
        logger.exception("Auto-research failed for flagged content")


# ── Commands ──────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Welcome to the AI Content Detection Bot!\n\n"
        "Send me any content — text, image, audio, or video — and I'll analyse it "
        "for signs of AI generation.\n\n"
        "Commands:\n"
        "/start — Show this welcome message\n"
        "/help — Show usage instructions\n"
        "/detect &lt;text&gt; — Analyse text directly\n"
        "/research &lt;query&gt; — Research a topic\n",
        parse_mode="HTML",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 <b>AI Content Detection Bot — Help</b>\n\n"
        "📝 <b>Text</b>: Send any text message to analyse\n"
        "🖼️ <b>Image</b>: Send a photo for visual AI-signal analysis\n"
        "🎤 <b>Audio</b>: Send a voice note or audio file for transcription + analysis\n"
        "🎬 <b>Video</b>: Send a video for frame + audio analysis\n\n"
        "All responses include a safety verdict and explanation.\n"
        "Supported languages: EN, ZH, MS, TA, Singlish.",
        parse_mode="HTML",
    )


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/detect <text> — Run detection on provided text."""
    args = context.args if hasattr(context, "args") else []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text("Usage: /detect &lt;text&gt;", parse_mode="HTML")
        return

    user_id = str(update.effective_user.id)
    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    try:
        # Step 1: Detect language
        source_lang = detect_language(text) if len(text) >= 20 else "en"

        # Step 2: Translate to English
        english_text = text
        if source_lang != "en":
            english_text = await translate_to_english(text, source_lang)

        # Step 3: Run full detection pipeline
        results = await run_full_detection(english_text, content_type="text", source_lang=source_lang)
        det = results["detection_result"]
        explanation = (results["insights_result"] or {}).get("explanation", "")

        # Step 4: Translate explanation back
        if source_lang != "en" and explanation:
            explanation = await translate_from_english(explanation, source_lang)

        response = format_detection_message(
            content_type="text",
            verdict=det.get("label", "Unknown"),
            is_safe=results.get("is_safe"),
            explanation=explanation,
            is_harmful=(results["insights_result"] or {}).get("is_harmful", False),
            misinfo_type=results.get("misinfo_type", "none"),
        )
        await update.message.reply_text(response, parse_mode="HTML")

        _schedule_log({
            "user_id": user_id,
            "content_type": "text",
            "source_language": source_lang,
            "content_preview": text[:500],
            "guard_label": det.get("label", ""),
            "guard_verdict": _verdict_str(det),
            "explanation": explanation,
        })
    except Exception as e:
        logger.exception("Error in detect_command")
        await update.message.reply_text("❌ Detection failed. Please try again later.")


async def research_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/research <query> — Search the web, summarise, reply with findings."""
    args = context.args if hasattr(context, "args") else []
    query = " ".join(args).strip()
    if not query:
        await update.message.reply_text("Usage: /research &lt;your question&gt;", parse_mode="HTML")
        return

    user_id = str(update.effective_user.id)
    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🔍 Researching, please wait...")

    source_lang = detect_language(query) if len(query) >= 20 else "en"

    try:
        from research_agent.agent import research

        result = await research(query)

        if result.get("error"):
            error_msg = result.get("error", "Research failed.")
            await update.message.reply_text(f"⚠️ {error_msg}")
            return

        if result.get("cache_hit") and result.get("skill_path"):
            skill_path = Path(result["skill_path"])
            if not skill_path.exists():
                await update.message.reply_text("⚠️ Cached research file was not found.")
                return
            skill_text = skill_path.read_text(encoding="utf-8")
            preview = skill_text[:800]
            response = f"📚 <b>Cached Skill Card</b>\n\n<pre>{preview}</pre>"
        elif result.get("summary_path"):
            summary_path = Path(result["summary_path"])
            if not summary_path.exists():
                await update.message.reply_text("⚠️ Research summary file was not found.")
                return
            summary_text = summary_path.read_text(encoding="utf-8")
            preview = summary_text[:800]
            response = (
                f"📝 <b>Research Summary</b>\n\n{preview}\n\n"
                f"({len(result.get('sources', []))} sources analysed)"
            )
        else:
            await update.message.reply_text("⚠️ No results found for your query.")
            return

        if source_lang != "en":
            response = await translate_from_english(response, source_lang)

        await update.message.reply_text(response, parse_mode="HTML")

        if result.get("summary_path"):
            with open(result["summary_path"], "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=Path(result["summary_path"]).name,
                )

        _schedule_log({
            "user_id": user_id,
            "content_type": "text",
            "source_language": source_lang,
            "content_preview": query[:500],
            "guard_verdict": "human_generated",
            "explanation": f"Research query: {query}",
        })
    except Exception as exc:
        logger.exception("Error in research_command")
        await update.message.reply_text(f"❌ Research failed. Please try again later.")


# ── Message handlers ──────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    raw_text = update.message.text
    user_id = str(update.effective_user.id)

    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    try:
        # Step 1: Detect language
        source_lang = detect_language(raw_text) if len(raw_text) >= 20 else "en"

        # Step 2: Translate to English
        english_text = raw_text
        if source_lang != "en":
            english_text = await translate_to_english(raw_text, source_lang)

        # Step 3: Run full detection pipeline
        results = await run_full_detection(english_text, content_type="text", source_lang=source_lang)
        det = results["detection_result"]
        misinfo = results["misinfo_result"]
        insights = results["insights_result"]

        explanation = (insights or {}).get("explanation", "Analysis unavailable.")
        is_harmful = (insights or {}).get("is_harmful", False)

        # Step 4: Translate explanation back
        if source_lang != "en":
            explanation = await translate_from_english(explanation, source_lang)

        # Step 5: Format and send
        response = format_detection_message(
            content_type="text",
            verdict=det.get("label", "Unknown"),
            is_safe=results.get("is_safe"),
            explanation=explanation,
            is_harmful=is_harmful,
            misinfo_type=results.get("misinfo_type", "none"),
        )
        await update.message.reply_text(response, parse_mode="HTML")

        # Step 6: Background tasks
        _schedule_background(
            _auto_research_if_flagged(
                english_text, det, misinfo, update, context, source_lang=source_lang,
            )
        )
        _schedule_log({
            "user_id": user_id,
            "content_type": "text",
            "source_language": source_lang,
            "content_preview": raw_text[:500],
            "guard_label": det.get("label", ""),
            "guard_verdict": _verdict_str(det),
            "misinfo_detected": (misinfo or {}).get("misinformation_detected", False),
            "misinfo_type": (misinfo or {}).get("misinformation_type", "none"),
            "explanation": explanation,
            "is_harmful": is_harmful,
        })

    except Exception as e:
        logger.exception("Error in handle_text")
        await update.message.reply_text("❌ Analysis failed. Please try again later.")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.photo:
        return

    user_id = str(update.effective_user.id)
    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🔍 Analysing image, please wait...")

    image_path = ""
    try:
        # Download photo
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        os.makedirs("downloads", exist_ok=True)
        image_path = f"downloads/{photo.file_id}.jpg"
        await file.download_to_drive(image_path)

        # Gemini visual analysis
        gemini_result = await analyse_image_with_gemini(image_path)
        caption = gemini_result.get("caption", "")
        ocr_text = gemini_result.get("ocr_text", "")
        ai_signals = gemini_result.get("ai_signals", "")

        # Language detection on OCR text
        source_lang = "en"
        if ocr_text and len(ocr_text) >= 20:
            source_lang = detect_language(ocr_text)

        # Translate OCR to English for detection
        ocr_english = ocr_text
        if source_lang != "en" and ocr_text:
            ocr_english = await translate_to_english(ocr_text, source_lang)

        # Build input for GUARD
        guard_input = f"Image description: {caption}"
        if ocr_english:
            guard_input += f"\nExtracted text: {ocr_english}"
        if ai_signals:
            guard_input += f"\nVisual AI signals: {ai_signals}"

        # Run full detection with image path
        results = await run_full_detection(
            guard_input, content_type="image", source_lang="en", image_path=image_path,
        )
        det = results["detection_result"]
        misinfo = results["misinfo_result"]
        manip = results["manipulation_result"]
        insights = results["insights_result"]

        explanation = (insights or {}).get("explanation", "Analysis unavailable.")
        is_harmful = (insights or {}).get("is_harmful", False)

        if source_lang != "en":
            explanation = await translate_from_english(explanation, source_lang)

        response = format_detection_message(
            content_type="image",
            verdict=det.get("label", "Unknown"),
            is_safe=results.get("is_safe"),
            explanation=explanation,
            is_harmful=is_harmful,
            misinfo_type=results.get("misinfo_type", "none"),
            caption=caption,
            ocr_text=ocr_text,
            ai_signals=ai_signals,
        )
        await update.message.reply_text(response, parse_mode="HTML")

        _schedule_background(
            _auto_research_if_flagged(
                guard_input, det, misinfo, update, context, source_lang=source_lang,
            )
        )
        _schedule_log({
            "user_id": user_id,
            "content_type": "image",
            "content_preview": caption[:500],
            "guard_label": det.get("label", ""),
            "guard_verdict": _verdict_str(det),
            "misinfo_detected": (misinfo or {}).get("misinformation_detected", False),
            "manipulation_detected": (manip or {}).get("manipulation_detected", False),
            "explanation": explanation,
            "is_harmful": is_harmful,
        })

    except Exception as e:
        logger.exception("Error in handle_photo")
        await update.message.reply_text("❌ Image analysis failed. Please try again later.")
    finally:
        if image_path and os.path.exists(image_path):
            os.remove(image_path)


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    audio = update.message.voice or update.message.audio
    if not audio:
        return

    user_id = str(update.effective_user.id)
    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    await update.message.reply_text("🎤 Transcribing audio, please wait...")

    audio_path = ""
    tts_path = ""
    try:
        # Step 1: Download
        file = await context.bot.get_file(audio.file_id)
        os.makedirs("downloads", exist_ok=True)
        ext = ".ogg" if update.message.voice else ".mp3"
        audio_path = f"downloads/{audio.file_id}{ext}"
        await file.download_to_drive(audio_path)

        # Step 2: Transcribe with Deepgram
        transcript_result = await transcribe_audio(audio_path)
        transcript = transcript_result.get("transcript", "")

        if not transcript:
            await update.message.reply_text(
                "⚠️ Could not transcribe audio. Please try a clearer recording."
            )
            return

        # Step 3: Use Deepgram's detected_language (NOT langdetect)
        source_lang = transcript_result.get("detected_language", "en")

        # Step 4: Translate to English
        english_text = transcript
        if source_lang != "en":
            english_text = await translate_to_english(transcript, source_lang)

        # Step 5: GUARD + misinformation
        results = await run_full_detection(english_text, content_type="audio", source_lang=source_lang)
        det = results["detection_result"]
        insights = results["insights_result"]

        explanation = (insights or {}).get("explanation", "Analysis unavailable.")
        is_harmful = (insights or {}).get("is_harmful", False)

        # Step 6: Translate back
        if source_lang != "en":
            explanation = await translate_from_english(explanation, source_lang)

        # Step 7: Format and send
        response = format_detection_message(
            content_type="audio",
            verdict=det.get("label", "Unknown"),
            is_safe=results.get("is_safe"),
            explanation=explanation,
            is_harmful=is_harmful,
            misinfo_type=results.get("misinfo_type", "none"),
            transcript=transcript,
        )
        await update.message.reply_text(response, parse_mode="HTML")

        # Step 8: Voice reply — try Gemini Live API first, fall back to ElevenLabs
        try:
            try:
                await context.bot.send_chat_action(
                    chat_id=update.effective_chat.id, action="record_voice"
                )
            except TelegramError as e:
                logger.info("[Audio] record_voice chat action skipped: %s", e)
            except Exception:
                pass

            with open(audio_path, "rb") as f:
                raw_audio = f.read()
            live_ogg = b""
            if live is not None:
                try:
                    live_ogg = await asyncio.wait_for(
                        live.live_voice_exchange(
                            audio_bytes=raw_audio,
                            mime_type="audio/ogg" if ext == ".ogg" else "audio/mpeg",
                            system_context=explanation,
                        ),
                        timeout=LIVE_API_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "[Audio] Live API voice reply timed out for user_id=%s",
                        user_id,
                    )
            if live_ogg:
                tts_path = f"downloads/live_{audio.file_id}.ogg"
                with open(tts_path, "wb") as f:
                    f.write(live_ogg)
                with open(tts_path, "rb") as voice_file:
                    await update.message.reply_voice(voice=voice_file)
            else:
                # Fallback to ElevenLabs TTS
                tts_path = f"downloads/tts_{audio.file_id}.mp3"
                tts_output = await synthesise_speech(explanation, tts_path, language=source_lang)
                if tts_output:
                    with open(tts_path, "rb") as voice_file:
                        await update.message.reply_voice(voice=voice_file)
        except Exception:
            logger.info("TTS reply skipped — Live API and ElevenLabs both unavailable")

        # Background tasks
        _schedule_background(
            _auto_research_if_flagged(
                english_text, det, results.get("misinfo_result"), update, context,
                source_lang=source_lang,
            )
        )
        _schedule_log({
            "user_id": user_id,
            "content_type": "audio",
            "source_language": source_lang,
            "content_preview": transcript[:500],
            "guard_label": det.get("label", ""),
            "guard_verdict": _verdict_str(det),
            "explanation": explanation,
            "is_harmful": is_harmful,
        })

    except Exception as e:
        logger.exception("Error in handle_audio")
        await update.message.reply_text("❌ Audio analysis failed. Please try again later.")
    finally:
        for p in (audio_path, tts_path):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    video = update.message.video or update.message.video_note
    if not video:
        return

    user_id = str(update.effective_user.id)
    if not await _check_rate_limit(user_id, update):
        return

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="upload_video")
    except Exception:
        pass

    await update.message.reply_text("🎬 Analysing video, please wait... This may take a moment.")

    video_path = ""
    try:
        # Step 1: Download
        file = await context.bot.get_file(video.file_id)
        os.makedirs("downloads", exist_ok=True)
        video_path = f"downloads/{video.file_id}.mp4"
        await file.download_to_drive(video_path)

        # Step 2: Analyse video (frames + audio)
        video_result = await analyse_video(video_path)

        if video_result.get("error") and not video_result.get("frame_descriptions"):
            await update.message.reply_text(
                "⚠️ Video analysis could not be completed. Please try a different video."
            )
            return

        # Step 3: Build guard input
        frame_text = " | ".join(video_result.get("frame_descriptions", []))
        audio_text = video_result.get("audio_transcript", "")
        ai_signals = video_result.get("ai_signals", "")

        # Step 4: Language detection on audio — translate before building guard_input
        source_lang = "en"
        audio_for_guard = audio_text
        if audio_text and len(audio_text) >= 20:
            source_lang = detect_language(audio_text)
            if source_lang != "en":
                audio_for_guard = await translate_to_english(audio_text, source_lang)

        guard_input = f"Video frame descriptions: {frame_text}"
        if audio_for_guard:
            guard_input += f"\nAudio transcript: {audio_for_guard}"
        if ai_signals:
            guard_input += f"\nVisual AI signals: {ai_signals}"

        # Step 5: Run detection pipeline
        results = await run_full_detection(guard_input, content_type="video", source_lang="en")
        det = results["detection_result"]
        insights = results["insights_result"]

        explanation = (insights or {}).get("explanation", "Analysis unavailable.")
        is_harmful = (insights or {}).get("is_harmful", False)

        if source_lang != "en":
            explanation = await translate_from_english(explanation, source_lang)

        # Step 6: Format and send
        response = format_detection_message(
            content_type="video",
            verdict=det.get("label", "Unknown"),
            is_safe=results.get("is_safe"),
            explanation=explanation,
            is_harmful=is_harmful,
            misinfo_type=results.get("misinfo_type", "none"),
            transcript=audio_text,
            ai_signals=ai_signals,
            frames_checked=video_result.get("frames_checked", 0),
        )
        await update.message.reply_text(response, parse_mode="HTML")

        _schedule_background(
            _auto_research_if_flagged(
                guard_input, det, results.get("misinfo_result"), update, context,
                source_lang=source_lang,
            )
        )
        _schedule_log({
            "user_id": user_id,
            "content_type": "video",
            "source_language": source_lang,
            "content_preview": frame_text[:500],
            "guard_label": det.get("label", ""),
            "guard_verdict": _verdict_str(det),
            "explanation": explanation,
            "is_harmful": is_harmful,
        })

    except Exception as e:
        logger.exception("Error in handle_video")
        await update.message.reply_text("❌ Video analysis failed. Please try again later.")
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass


# ── Cloud Run health check server ─────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass  # suppress access logs


def _start_health_server():
    """Start a minimal HTTP server on PORT for Cloud Run health checks."""
    port = HEALTH_PORT
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Health check server listening on port %d", port)
    except OSError as exc:
        logger.warning(
            "Health check server could not bind to port %d: %s. "
            "Bot will continue without health endpoint.",
            port, exc,
        )


# ── Bot startup ───────────────────────────────────────────────────────

def _build_app():
    """Build the Telegram Application with all handlers."""
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start_command))
    bot_app.add_handler(CommandHandler("help", help_command))
    bot_app.add_handler(CommandHandler("detect", detect_command))
    bot_app.add_handler(CommandHandler("research", research_command))
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    bot_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_audio))
    bot_app.add_handler(MessageHandler(filters.VIDEO | filters.VIDEO_NOTE, handle_video))
    return bot_app


async def init_webhook_app() -> bool:
    """Initialise Telegram application for webhook update processing."""
    global _webhook_app

    if _webhook_app is not None:
        return True
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set — Telegram webhook app will not start")
        return False

    async with _webhook_app_lock:
        if _webhook_app is not None:
            return True

        bot_app = _build_app()
        try:
            await bot_app.initialize()
            await bot_app.start()

            if TELEGRAM_WEBHOOK_URL:
                webhook_kwargs = {}
                if TELEGRAM_WEBHOOK_SECRET:
                    webhook_kwargs["secret_token"] = TELEGRAM_WEBHOOK_SECRET
                await bot_app.bot.set_webhook(url=TELEGRAM_WEBHOOK_URL, **webhook_kwargs)

            _webhook_app = bot_app
            logger.info("Telegram webhook application initialised")
            return True
        except Exception:
            logger.exception("Failed to initialise Telegram webhook application")
            try:
                await bot_app.stop()
            except Exception:
                pass
            try:
                await bot_app.shutdown()
            except Exception:
                pass
            return False


async def shutdown_webhook_app() -> None:
    """Shutdown Telegram webhook application cleanly."""
    global _webhook_app

    async with _webhook_app_lock:
        bot_app = _webhook_app
        _webhook_app = None

    if bot_app is None:
        return

    try:
        await bot_app.stop()
    except Exception:
        logger.debug("Webhook app stop failed", exc_info=True)
    try:
        await bot_app.shutdown()
    except Exception:
        logger.debug("Webhook app shutdown failed", exc_info=True)


async def process_webhook_update(payload: dict) -> bool:
    """Process a Telegram webhook update payload via PTB dispatcher."""
    global _webhook_app

    try:
        if not await init_webhook_app():
            return False
        if _webhook_app is None:
            return False

        update = Update.de_json(payload, _webhook_app.bot)
        if update is None:
            return False

        await _webhook_app.process_update(update)
        return True
    except Exception:
        logger.exception("Failed to process Telegram webhook update")
        return False


def get_telegram_runtime_status() -> dict:
    """Return lightweight runtime status for health diagnostics."""
    webhook_ready = _webhook_app is not None
    webhook_running = bool(getattr(_webhook_app, "running", False)) if webhook_ready else False
    return {
        "webhook_ready": webhook_ready,
        "webhook_running": webhook_running,
        "webhook_enabled": TELEGRAM_WEBHOOK_ENABLED,
    }


def start_bot_background():
    """Start the Telegram bot poller in a daemon thread (non-blocking).

    Use this when running alongside FastAPI (e.g. on Cloud Run).
    """
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_TOKEN not set — Telegram bot will not start")
        return
    if TELEGRAM_WEBHOOK_ENABLED:
        logger.info("Telegram webhook mode enabled — skipping polling startup")
        return

    def _run():
        bot_app = _build_app()
        logger.info("Starting Telegram bot polling (background thread)...")
        # PTB installs signal handlers by default; disable them in non-main threads.
        bot_app.run_polling(bootstrap_retries=5, stop_signals=None)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def start_bot():
    """Initialise and start the Telegram bot (blocking — for standalone use)."""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN not set — cannot start bot")
        sys.exit(1)
    if TELEGRAM_WEBHOOK_ENABLED:
        logger.error("TELEGRAM_WEBHOOK_ENABLED=true — polling mode disabled")
        sys.exit(1)

    # Standalone mode: start health server for Cloud Run
    _start_health_server()

    bot_app = _build_app()
    logger.info("Starting Telegram bot polling...")
    bot_app.run_polling(bootstrap_retries=5)


if __name__ == "__main__":
    start_bot()

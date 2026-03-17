"""Tests for telegram_bot.py — handlers, commands, rate limiting, and bot setup.

All external dependencies are mocked. Zero real network calls.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────

def _make_update(
    text: str = "Hello world test message",
    user_id: int = 12345,
    chat_id: int = 67890,
    photo: list | None = None,
    voice: object | None = None,
    audio: object | None = None,
    video: object | None = None,
    video_note: object | None = None,
):
    """Build a fake telegram.Update with controlled attributes."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id

    msg = MagicMock()
    msg.text = text
    msg.photo = photo or []
    msg.voice = voice
    msg.audio = audio
    msg.video = video
    msg.video_note = video_note
    msg.reply_text = AsyncMock()
    msg.reply_voice = AsyncMock()
    update.message = msg

    return update


def _make_context(args: list[str] | None = None):
    """Build a fake ContextTypes.DEFAULT_TYPE context."""
    ctx = MagicMock()
    ctx.args = args or []
    ctx.bot.send_chat_action = AsyncMock()
    ctx.bot.get_file = AsyncMock()
    ctx.bot.send_document = AsyncMock()
    return ctx


def _detection_result(
    is_safe: bool | None = True,
    label: str = "safe",
):
    return {
        "is_safe": is_safe,
        "label": label,
        "raw_response": {},
        "safety_flag": "unsafe" if is_safe is False else None,
    }


def _misinfo_result(detected: bool = False):
    return {
        "misinformation_detected": detected,
        "misinformation_type": "none",
        "claims": [],
        "explanation": "No issues found.",
        "confidence": 0.0,
    }


def _insights_result(explanation: str = "Content appears genuine.", harmful: bool = False):
    return {
        "explanation": explanation,
        "is_harmful": harmful,
        "llm_used": "gemini",
    }


def _full_detection_result(**overrides):
    """Standard run_full_detection return dict."""
    base = {
        "detection_result": _detection_result(),
        "misinfo_result": _misinfo_result(),
        "manipulation_result": None,
        "insights_result": _insights_result(),
        "is_safe": True,
        "misinfo_type": "none",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Clear the module-level rate-limit dict between tests."""
    import telegram_bot
    telegram_bot._user_last_request.clear()
    yield
    telegram_bot._user_last_request.clear()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1 — RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_first_request_passes(self):
        """First request from a user should always pass rate limiting."""
        from telegram_bot import _check_rate_limit

        update = _make_update()
        result = await _check_rate_limit("user1", update)
        assert result is True

    @pytest.mark.asyncio
    async def test_rapid_request_blocked(self):
        """Second request within cooldown window should be blocked."""
        from telegram_bot import _check_rate_limit

        update = _make_update()
        await _check_rate_limit("user2", update)
        result = await _check_rate_limit("user2", update)
        assert result is False
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_different_users_independent(self):
        """Rate limit should be per-user, not global."""
        from telegram_bot import _check_rate_limit

        update_a = _make_update(user_id=1)
        update_b = _make_update(user_id=2)
        await _check_rate_limit("user_a", update_a)
        result = await _check_rate_limit("user_b", update_b)
        assert result is True

    @pytest.mark.asyncio
    async def test_reply_text_error_swallowed(self):
        """If reply_text raises during rate limit, it should not propagate."""
        from telegram_bot import _check_rate_limit
        import telegram_bot

        update = _make_update()
        telegram_bot._user_last_request["user3"] = asyncio.get_event_loop().time()
        update.message.reply_text = AsyncMock(side_effect=RuntimeError("network"))
        result = await _check_rate_limit("user3", update)
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2 — UTILITY FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════

class TestVerdictStr:
    def test_safe(self):
        from telegram_bot import _verdict_str

        assert _verdict_str({"is_safe": True}) == "safe"

    def test_unsafe(self):
        from telegram_bot import _verdict_str

        assert _verdict_str({"is_safe": False}) == "unsafe"

    def test_inconclusive(self):
        from telegram_bot import _verdict_str

        assert _verdict_str({"is_safe": None}) == "inconclusive"

    def test_missing_key(self):
        from telegram_bot import _verdict_str

        assert _verdict_str({}) == "inconclusive"


class TestScheduleLog:
    def test_never_raises(self):
        """_schedule_log must never raise, even if create_task fails."""
        from telegram_bot import _schedule_log

        with patch("telegram_bot.asyncio.create_task", side_effect=RuntimeError("no loop")):
            _schedule_log({"user_id": "test"})

    def test_calls_create_task(self):
        from telegram_bot import _schedule_log

        with patch("telegram_bot.asyncio.create_task") as mock_task:
            _schedule_log({"user_id": "test"})
            mock_task.assert_called_once()


class TestScheduleBackground:
    def test_closes_coro_when_create_task_fails(self):
        from telegram_bot import _schedule_background

        async def _noop():
            return None

        coro = _noop()
        with patch("telegram_bot.asyncio.create_task", side_effect=RuntimeError("no loop")):
            _schedule_background(coro)

        assert coro.cr_frame is None

    def test_closes_coro_when_create_task_is_mocked(self):
        from telegram_bot import _schedule_background

        async def _noop():
            return None

        coro = _noop()
        with patch("telegram_bot.asyncio.create_task", return_value=MagicMock()):
            _schedule_background(coro)

        assert coro.cr_frame is None


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3 — /start AND /help COMMANDS
# ═══════════════════════════════════════════════════════════════════════

class TestStartCommand:
    @pytest.mark.asyncio
    async def test_sends_welcome(self):
        from telegram_bot import start_command

        update = _make_update()
        ctx = _make_context()
        await start_command(update, ctx)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert call_kwargs.kwargs.get("parse_mode") == "HTML"
        assert "Welcome" in call_kwargs.args[0]


class TestHelpCommand:
    @pytest.mark.asyncio
    async def test_sends_help(self):
        from telegram_bot import help_command

        update = _make_update()
        ctx = _make_context()
        await help_command(update, ctx)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert call_kwargs.kwargs.get("parse_mode") == "HTML"
        assert "Help" in call_kwargs.args[0]


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4 — /detect COMMAND
# ═══════════════════════════════════════════════════════════════════════

class TestDetectCommand:
    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self):
        from telegram_bot import detect_command

        update = _make_update()
        ctx = _make_context(args=[])
        await detect_command(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "Usage" in update.message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_successful_detection(self):
        from telegram_bot import detect_command

        update = _make_update()
        ctx = _make_context(args=["This", "is", "AI", "generated", "text"])

        with patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message") as mock_fmt, \
             patch("telegram_bot._schedule_log"):
            mock_det.return_value = _full_detection_result()
            mock_fmt.return_value = "<b>Result</b>"

            await detect_command(update, ctx)

            mock_det.assert_called_once()
            mock_fmt.assert_called_once()
            update.message.reply_text.assert_called()
            # Should reply with HTML
            final_call = update.message.reply_text.call_args_list[-1]
            assert final_call.kwargs.get("parse_mode") == "HTML"

    @pytest.mark.asyncio
    async def test_rate_limited(self):
        """detect_command should respect rate limiting."""
        from telegram_bot import detect_command
        import telegram_bot

        update = _make_update()
        ctx = _make_context(args=["test"])
        telegram_bot._user_last_request[str(update.effective_user.id)] = (
            asyncio.get_event_loop().time()
        )

        with patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det:
            await detect_command(update, ctx)
            mock_det.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_reports_error(self):
        from telegram_bot import detect_command

        update = _make_update()
        ctx = _make_context(args=["test", "text"])

        with patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det:
            mock_det.side_effect = RuntimeError("pipeline exploded")
            await detect_command(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "failed" in last_reply.lower() or "❌" in last_reply


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5 — /research COMMAND
# ═══════════════════════════════════════════════════════════════════════

class TestResearchCommand:
    @pytest.mark.asyncio
    async def test_no_args_shows_usage(self):
        from telegram_bot import research_command

        update = _make_update()
        ctx = _make_context(args=[])
        await research_command(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "Usage" in update.message.reply_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_successful_research_with_summary(self, tmp_path):
        from telegram_bot import research_command

        summary_file = tmp_path / "summary.md"
        summary_file.write_text("# Summary\nResearch findings here.", encoding="utf-8")

        update = _make_update()
        ctx = _make_context(args=["deepfake", "detection", "methods"])

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research, \
             patch("telegram_bot._schedule_log"):
            mock_research.return_value = {
                "cache_hit": False,
                "summary_path": str(summary_file),
                "sources": ["https://example.com"],
            }

            await research_command(update, ctx)

            replies = update.message.reply_text.call_args_list
            # Should have "Researching..." then the summary reply
            assert len(replies) >= 2
            summary_reply = replies[-1]
            assert summary_reply.kwargs.get("parse_mode") == "HTML"

    @pytest.mark.asyncio
    async def test_no_results_found(self):
        from telegram_bot import research_command

        update = _make_update()
        ctx = _make_context(args=["obscure", "query"])

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            mock_research.return_value = {}

            await research_command(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "No results" in last_reply

    @pytest.mark.asyncio
    async def test_exception_reports_error(self):
        from telegram_bot import research_command

        update = _make_update()
        ctx = _make_context(args=["test"])

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            mock_research.side_effect = RuntimeError("Firecrawl down")
            await research_command(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "failed" in last_reply.lower() or "❌" in last_reply


# ═══════════════════════════════════════════════════════════════════════
# SECTION 6 — handle_text
# ═══════════════════════════════════════════════════════════════════════

class TestHandleText:
    @pytest.mark.asyncio
    async def test_skips_when_no_message(self):
        from telegram_bot import handle_text

        update = MagicMock()
        update.message = None
        ctx = _make_context()
        await handle_text(update, ctx)
        # Should return early with no error

    @pytest.mark.asyncio
    async def test_skips_when_no_text(self):
        from telegram_bot import handle_text

        update = _make_update(text=None)
        update.message.text = None
        ctx = _make_context()
        await handle_text(update, ctx)

    @pytest.mark.asyncio
    async def test_english_text_full_pipeline(self):
        """English text goes through detect_language -> run_full_detection -> format -> reply."""
        from telegram_bot import handle_text

        update = _make_update(text="This is a definitely long enough test message for detection")
        ctx = _make_context()

        with patch("telegram_bot.detect_language", return_value="en") as mock_lang, \
             patch("telegram_bot.translate_to_english", new_callable=AsyncMock) as mock_to_en, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message") as mock_fmt, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_from_en, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"):

            mock_det.return_value = _full_detection_result()
            mock_fmt.return_value = "<b>Analysis</b>"

            await handle_text(update, ctx)

            mock_lang.assert_called_once()
            # English text should NOT trigger translate_to_english
            mock_to_en.assert_not_called()
            mock_det.assert_called_once()
            mock_fmt.assert_called_once()
            # English text should NOT trigger translate_from_english
            mock_from_en.assert_not_called()

            final_reply = update.message.reply_text.call_args
            assert final_reply.kwargs.get("parse_mode") == "HTML"

    @pytest.mark.asyncio
    async def test_non_english_text_triggers_translation(self):
        """Non-EN text should translate to English before detection, translate back after."""
        from telegram_bot import handle_text

        update = _make_update(text="这是一个很长的中文文本用于测试检测流程的翻译功能")
        ctx = _make_context()

        with patch("telegram_bot.detect_language", return_value="zh") as mock_lang, \
             patch("telegram_bot.translate_to_english", new_callable=AsyncMock) as mock_to_en, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message") as mock_fmt, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_from_en, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"):

            mock_to_en.return_value = "This is a long Chinese text"
            mock_det.return_value = _full_detection_result()
            mock_fmt.return_value = "<b>Result</b>"
            mock_from_en.return_value = "翻译后的解释"

            await handle_text(update, ctx)

            mock_to_en.assert_called_once()
            mock_from_en.assert_called_once()

    @pytest.mark.asyncio
    async def test_short_text_defaults_to_english(self):
        """Text under 20 chars should default to source_lang='en' — no langdetect call."""
        from telegram_bot import handle_text

        update = _make_update(text="Hi there")
        ctx = _make_context()

        with patch("telegram_bot.detect_language") as mock_lang, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message") as mock_fmt, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"):

            mock_det.return_value = _full_detection_result()
            mock_fmt.return_value = "<b>OK</b>"

            await handle_text(update, ctx)

            # detect_language should NOT be called for text < 20 chars
            mock_lang.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_sends_error_to_user(self):
        from telegram_bot import handle_text

        update = _make_update(text="This is definitely long enough text for testing errors")
        ctx = _make_context()

        with patch("telegram_bot.detect_language", side_effect=RuntimeError("boom")):
            await handle_text(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "❌" in last_reply or "failed" in last_reply.lower()

    @pytest.mark.asyncio
    async def test_logs_to_clickhouse(self):
        """handle_text should schedule a ClickHouse log entry."""
        from telegram_bot import handle_text

        update = _make_update(text="Testing the logging path for long enough messages")
        ctx = _make_context()

        with patch("telegram_bot.detect_language", return_value="en"), \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>OK</b>"), \
             patch("telegram_bot._schedule_log") as mock_log, \
             patch("telegram_bot.asyncio.create_task"):

            mock_det.return_value = _full_detection_result()

            await handle_text(update, ctx)

            mock_log.assert_called_once()
            log_row = mock_log.call_args.args[0]
            assert log_row["content_type"] == "text"
            assert "user_id" in log_row

    @pytest.mark.asyncio
    async def test_auto_research_triggered_for_unsafe_content(self):
        """When unsafe, auto-research background task should be created."""
        from telegram_bot import handle_text

        update = _make_update(text="This is a long enough text to trigger the auto research path")
        ctx = _make_context()

        ai_det = _detection_result(is_safe=False, label="unsafe")
        full = _full_detection_result(detection_result=ai_det, is_safe=False)

        with patch("telegram_bot.detect_language", return_value="en"), \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock, return_value=full), \
             patch("telegram_bot.format_detection_message", return_value="<b>AI</b>"), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task") as mock_task:

            await handle_text(update, ctx)

            # asyncio.create_task should be called for auto-research
            mock_task.assert_called()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 7 — handle_photo
# ═══════════════════════════════════════════════════════════════════════

class TestHandlePhoto:
    @pytest.mark.asyncio
    async def test_skips_when_no_photo(self):
        from telegram_bot import handle_photo

        update = _make_update()
        update.message.photo = []
        ctx = _make_context()
        await handle_photo(update, ctx)

    @pytest.mark.asyncio
    async def test_full_photo_pipeline(self, tmp_path):
        from telegram_bot import handle_photo

        photo_mock = MagicMock()
        photo_mock.file_id = "test_photo_id"
        update = _make_update(photo=[photo_mock])

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_image_with_gemini", new_callable=AsyncMock) as mock_gemini, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message") as mock_fmt, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_gemini.return_value = {
                "caption": "A photo of a sunset",
                "ocr_text": "",
                "ai_signals": "no anomalies",
                "raw_response": "...",
            }
            mock_det.return_value = _full_detection_result()
            mock_fmt.return_value = "<b>Image analysis</b>"

            await handle_photo(update, ctx)

            ctx.bot.get_file.assert_called_once()
            file_mock.download_to_drive.assert_called_once()
            mock_gemini.assert_called_once()
            mock_det.assert_called_once()
            # run_full_detection should receive image_path
            call_kwargs = mock_det.call_args.kwargs
            assert "image_path" in call_kwargs

    @pytest.mark.asyncio
    async def test_photo_with_ocr_triggers_translation(self):
        """Photo with non-English OCR text should trigger translation."""
        from telegram_bot import handle_photo

        photo_mock = MagicMock()
        photo_mock.file_id = "ocr_photo"
        update = _make_update(photo=[photo_mock])

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_image_with_gemini", new_callable=AsyncMock) as mock_gemini, \
             patch("telegram_bot.detect_language", return_value="zh") as mock_lang, \
             patch("telegram_bot.translate_to_english", new_callable=AsyncMock) as mock_to_en, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_from_en, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>R</b>"), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_gemini.return_value = {
                "caption": "A document",
                "ocr_text": "这是一段足够长的中文OCR文本用于语言检测",
                "ai_signals": "",
            }
            mock_to_en.return_value = "This is OCR text in English"
            mock_from_en.return_value = "翻译结果"
            mock_det.return_value = _full_detection_result()

            await handle_photo(update, ctx)

            mock_to_en.assert_called_once()
            mock_from_en.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_on_exception(self):
        """Image file must be cleaned up even on exception (finally block)."""
        from telegram_bot import handle_photo

        photo_mock = MagicMock()
        photo_mock.file_id = "cleanup_test"
        update = _make_update(photo=[photo_mock])

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_image_with_gemini", new_callable=AsyncMock) as mock_gemini, \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True) as mock_exists, \
             patch("os.remove") as mock_remove:

            mock_gemini.side_effect = RuntimeError("Gemini crashed")

            await handle_photo(update, ctx)

            # finally block should attempt removal
            mock_remove.assert_called()

    @pytest.mark.asyncio
    async def test_uses_html_parse_mode(self):
        from telegram_bot import handle_photo

        photo_mock = MagicMock()
        photo_mock.file_id = "html_check"
        update = _make_update(photo=[photo_mock])

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_image_with_gemini", new_callable=AsyncMock) as mock_g, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>OK</b>"), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_g.return_value = {"caption": "x", "ocr_text": "", "ai_signals": ""}
            mock_det.return_value = _full_detection_result()

            await handle_photo(update, ctx)

            # Find the call with parse_mode
            for call in update.message.reply_text.call_args_list:
                if call.kwargs.get("parse_mode"):
                    assert call.kwargs["parse_mode"] == "HTML"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 8 — handle_audio
# ═══════════════════════════════════════════════════════════════════════

class TestHandleAudio:
    @pytest.mark.asyncio
    async def test_skips_when_no_audio(self):
        from telegram_bot import handle_audio

        update = _make_update()
        update.message.voice = None
        update.message.audio = None
        ctx = _make_context()
        await handle_audio(update, ctx)

    @pytest.mark.asyncio
    async def test_voice_message_pipeline(self):
        from telegram_bot import handle_audio

        voice = MagicMock()
        voice.file_id = "voice_123"
        update = _make_update(voice=voice)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.transcribe_audio", new_callable=AsyncMock) as mock_stt, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>Audio</b>"), \
             patch("telegram_bot.synthesise_speech", new_callable=AsyncMock, return_value="") as mock_tts, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"):

            mock_stt.return_value = {
                "transcript": "Hello this is a test transcription result",
                "detected_language": "en",
                "confidence": 0.95,
                "duration_seconds": 5.0,
            }
            mock_det.return_value = _full_detection_result()

            await handle_audio(update, ctx)

            mock_stt.assert_called_once()
            mock_det.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_transcript_shows_warning(self):
        from telegram_bot import handle_audio

        voice = MagicMock()
        voice.file_id = "voice_empty"
        update = _make_update(voice=voice)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.transcribe_audio", new_callable=AsyncMock) as mock_stt, \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"):

            mock_stt.return_value = {"transcript": "", "detected_language": "en"}

            await handle_audio(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "Could not transcribe" in last_reply

    @pytest.mark.asyncio
    async def test_uses_deepgram_detected_language(self):
        """Audio handler uses Deepgram's detected_language, NOT langdetect."""
        from telegram_bot import handle_audio

        voice = MagicMock()
        voice.file_id = "voice_zh"
        update = _make_update(voice=voice)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.transcribe_audio", new_callable=AsyncMock) as mock_stt, \
             patch("telegram_bot.translate_to_english", new_callable=AsyncMock) as mock_to_en, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_from_en, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>R</b>"), \
             patch("telegram_bot.synthesise_speech", new_callable=AsyncMock, return_value=""), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"):

            mock_stt.return_value = {
                "transcript": "你好世界这是一个语音测试消息",
                "detected_language": "zh",
                "confidence": 0.9,
            }
            mock_to_en.return_value = "Hello world"
            mock_from_en.return_value = "翻译结果"
            mock_det.return_value = _full_detection_result()

            await handle_audio(update, ctx)

            # Should use Deepgram's "zh", NOT call detect_language
            mock_to_en.assert_called_once()
            mock_from_en.assert_called_once()

    @pytest.mark.asyncio
    async def test_tts_failure_swallowed(self):
        """TTS failure should not crash the handler."""
        from telegram_bot import handle_audio

        voice = MagicMock()
        voice.file_id = "voice_tts_fail"
        update = _make_update(voice=voice)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.transcribe_audio", new_callable=AsyncMock) as mock_stt, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>OK</b>"), \
             patch("telegram_bot.synthesise_speech", new_callable=AsyncMock) as mock_tts, \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=False), \
             patch("os.remove"):

            mock_stt.return_value = {
                "transcript": "Hello world test message for TTS failure",
                "detected_language": "en",
            }
            mock_det.return_value = _full_detection_result()
            mock_tts.side_effect = RuntimeError("ElevenLabs down")

            # Should not raise
            await handle_audio(update, ctx)

    @pytest.mark.asyncio
    async def test_audio_temp_files_cleaned_up(self):
        """Audio and TTS temp files must be cleaned up in finally block."""
        from telegram_bot import handle_audio

        voice = MagicMock()
        voice.file_id = "voice_cleanup"
        update = _make_update(voice=voice)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.transcribe_audio", new_callable=AsyncMock) as mock_stt, \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_remove:

            mock_stt.side_effect = RuntimeError("Deepgram error")

            await handle_audio(update, ctx)

            # os.remove should be called for cleanup
            assert mock_remove.call_count >= 1


# ═══════════════════════════════════════════════════════════════════════
# SECTION 9 — handle_video
# ═══════════════════════════════════════════════════════════════════════

class TestHandleVideo:
    @pytest.mark.asyncio
    async def test_skips_when_no_video(self):
        from telegram_bot import handle_video

        update = _make_update()
        update.message.video = None
        update.message.video_note = None
        ctx = _make_context()
        await handle_video(update, ctx)

    @pytest.mark.asyncio
    async def test_full_video_pipeline(self):
        from telegram_bot import handle_video

        video = MagicMock()
        video.file_id = "video_123"
        update = _make_update(video=video)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_video", new_callable=AsyncMock) as mock_vid, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>Video</b>"), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_vid.return_value = {
                "frame_descriptions": ["a sunset scene", "person talking"],
                "audio_transcript": "",
                "ai_signals": "none detected",
                "frames_checked": 5,
                "error": None,
            }
            mock_det.return_value = _full_detection_result()

            await handle_video(update, ctx)

            mock_vid.assert_called_once()
            mock_det.assert_called_once()

    @pytest.mark.asyncio
    async def test_video_with_audio_transcript_translation(self):
        """Video with non-English audio should trigger translation."""
        from telegram_bot import handle_video

        video = MagicMock()
        video.file_id = "video_zh"
        update = _make_update(video=video)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_video", new_callable=AsyncMock) as mock_vid, \
             patch("telegram_bot.detect_language", return_value="zh"), \
             patch("telegram_bot.translate_to_english", new_callable=AsyncMock) as mock_to_en, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_from_en, \
             patch("telegram_bot.run_full_detection", new_callable=AsyncMock) as mock_det, \
             patch("telegram_bot.format_detection_message", return_value="<b>V</b>"), \
             patch("telegram_bot._schedule_log"), \
             patch("telegram_bot.asyncio.create_task"), \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_vid.return_value = {
                "frame_descriptions": ["scene"],
                "audio_transcript": "这是一段非常长的音频转录文本用于完整的语言检测",
                "ai_signals": "",
                "frames_checked": 1,
                "error": None,
            }
            mock_to_en.return_value = "This is the English translation"
            mock_from_en.return_value = "翻译后"
            mock_det.return_value = _full_detection_result()

            await handle_video(update, ctx)

            mock_to_en.assert_called_once()
            mock_from_en.assert_called_once()

    @pytest.mark.asyncio
    async def test_video_analysis_error_shows_message(self):
        """When video analysis fails with error and no frames, show warning."""
        from telegram_bot import handle_video

        video = MagicMock()
        video.file_id = "video_err"
        update = _make_update(video=video)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_video", new_callable=AsyncMock) as mock_vid, \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"):

            mock_vid.return_value = {
                "frame_descriptions": [],
                "audio_transcript": "",
                "ai_signals": "",
                "frames_checked": 0,
                "error": "ffmpeg not found",
            }

            await handle_video(update, ctx)

            last_reply = update.message.reply_text.call_args_list[-1].args[0]
            assert "failed" in last_reply.lower() or "⚠️" in last_reply

    @pytest.mark.asyncio
    async def test_video_cleanup_on_exception(self):
        from telegram_bot import handle_video

        video = MagicMock()
        video.file_id = "video_cleanup"
        update = _make_update(video=video)

        file_mock = MagicMock()
        file_mock.download_to_drive = AsyncMock()
        ctx = _make_context()
        ctx.bot.get_file = AsyncMock(return_value=file_mock)

        with patch("telegram_bot.analyse_video", new_callable=AsyncMock) as mock_vid, \
             patch("os.makedirs"), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove") as mock_remove:

            mock_vid.side_effect = RuntimeError("crashed")

            await handle_video(update, ctx)

            mock_remove.assert_called()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 10 — AUTO-RESEARCH
# ═══════════════════════════════════════════════════════════════════════

class TestAutoResearch:
    @pytest.mark.asyncio
    async def test_skips_when_not_flagged(self):
        from telegram_bot import _auto_research_if_flagged

        update = _make_update()
        ctx = _make_context()

        det = _detection_result(is_safe=True)
        misinfo = _misinfo_result(detected=False)

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            await _auto_research_if_flagged("text", det, misinfo, update, ctx)
            # Should not attempt research
            mock_research.assert_not_called()

    @pytest.mark.asyncio
    async def test_triggers_when_unsafe_detected(self, tmp_path):
        from telegram_bot import _auto_research_if_flagged

        summary_file = tmp_path / "summary.md"
        summary_file.write_text("# Research findings", encoding="utf-8")

        update = _make_update()
        ctx = _make_context()

        det = _detection_result(is_safe=False)
        misinfo = _misinfo_result(detected=False)

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            mock_research.return_value = {
                "summary_path": str(summary_file),
                "sources": ["https://example.com"],
            }

            await _auto_research_if_flagged("text", det, misinfo, update, ctx)

            mock_research.assert_called_once()
            # Should reply with research results
            update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_triggers_when_misinfo_detected(self, tmp_path):
        from telegram_bot import _auto_research_if_flagged

        summary_file = tmp_path / "summary.md"
        summary_file.write_text("# Misinfo check", encoding="utf-8")

        update = _make_update()
        ctx = _make_context()

        det = _detection_result(is_safe=True)
        misinfo = _misinfo_result(detected=True)

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            mock_research.return_value = {
                "summary_path": str(summary_file),
                "sources": [],
            }

            await _auto_research_if_flagged("text", det, misinfo, update, ctx)

            mock_research.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_swallowed(self):
        """Auto-research failure must never crash the handler."""
        from telegram_bot import _auto_research_if_flagged

        update = _make_update()
        ctx = _make_context()

        det = _detection_result(is_safe=False)

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research:
            mock_research.side_effect = RuntimeError("Firecrawl down")

            # Should not raise
            await _auto_research_if_flagged("text", det, None, update, ctx)

    @pytest.mark.asyncio
    async def test_translates_when_non_english(self, tmp_path):
        from telegram_bot import _auto_research_if_flagged

        summary_file = tmp_path / "summary.md"
        summary_file.write_text("# Research", encoding="utf-8")

        update = _make_update()
        ctx = _make_context()

        det = _detection_result(is_safe=False)

        with patch("research_agent.agent.research", new_callable=AsyncMock) as mock_research, \
             patch("telegram_bot.translate_from_english", new_callable=AsyncMock) as mock_trans:

            mock_research.return_value = {
                "summary_path": str(summary_file),
                "sources": [],
            }
            mock_trans.return_value = "翻译研究结果"

            await _auto_research_if_flagged(
                "text", det, None, update, ctx, source_lang="zh"
            )

            mock_trans.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# SECTION 11 — BOT STARTUP
# ═══════════════════════════════════════════════════════════════════════

class TestStartBot:
    def test_exits_without_token(self):
        from telegram_bot import start_bot

        with patch("telegram_bot.TELEGRAM_TOKEN", ""):
            with pytest.raises(SystemExit):
                start_bot()

    def test_registers_all_handlers(self):
        from telegram_bot import start_bot

        with patch("telegram_bot.TELEGRAM_TOKEN", "fake-token"), \
             patch("telegram_bot.ApplicationBuilder") as mock_builder:

            mock_app = MagicMock()
            mock_builder.return_value.token.return_value.build.return_value = mock_app
            mock_app.run_polling = MagicMock()

            start_bot()

            # Should register all handlers
            assert mock_app.add_handler.call_count >= 8
            mock_app.run_polling.assert_called_once()

    def test_background_start_disables_signal_handlers(self):
        from telegram_bot import start_bot_background

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target
                self.daemon = daemon

            def start(self):
                self._target()

        mock_app = MagicMock()
        with patch("telegram_bot.TELEGRAM_TOKEN", "fake-token"), \
             patch("telegram_bot._build_app", return_value=mock_app), \
             patch(
                 "telegram_bot.threading.Thread",
                 side_effect=lambda target, daemon: _InlineThread(target=target, daemon=daemon),
             ):
            start_bot_background()

        mock_app.run_polling.assert_called_once_with(
            bootstrap_retries=5,
            stop_signals=None,
        )


# ═══════════════════════════════════════════════════════════════════════
# SECTION 12 — PARSE MODE COMPLIANCE
# ═══════════════════════════════════════════════════════════════════════

class TestParseModeCompliance:
    """Verify every handler uses parse_mode='HTML' — never MarkdownV2."""

    def test_no_markdownv2_in_source(self):
        """Source code should never contain parse_mode='MarkdownV2'."""
        import inspect
        import telegram_bot

        source = inspect.getsource(telegram_bot)
        assert 'parse_mode="MarkdownV2"' not in source
        assert "parse_mode='MarkdownV2'" not in source
        assert 'parse_mode="Markdown"' not in source
        assert "parse_mode='Markdown'" not in source

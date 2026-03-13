"""Tests for pipeline/translator.py."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest


class TestDetectLanguage:
    def test_returns_en_for_short_text(self):
        from pipeline.translator import detect_language
        assert detect_language("hello") == "en"
        assert detect_language("hi") == "en"
        assert detect_language("") == "en"

    def test_returns_zh_for_chinese(self):
        with patch("pipeline.translator.detect", return_value="zh-cn"):
            from pipeline.translator import detect_language
            assert detect_language("这是一段足够长的中文文本，用于语言检测测试场景的验证") == "zh"

    def test_returns_ms_for_malay(self):
        with patch("pipeline.translator.detect", return_value="ms"):
            from pipeline.translator import detect_language
            assert detect_language("Ini adalah teks ujian yang cukup panjang") == "ms"

    def test_maps_indonesian_to_malay(self):
        with patch("pipeline.translator.detect", return_value="id"):
            from pipeline.translator import detect_language
            assert detect_language("Ini adalah contoh teks Indonesia yang cukup panjang") == "ms"

    def test_returns_ta_for_tamil(self):
        with patch("pipeline.translator.detect", return_value="ta"):
            from pipeline.translator import detect_language
            assert detect_language("இது மொழி கண்டறிதல் சோதனைக்கான போதுமான நீளமான தமிழ் உரை") == "ta"

    def test_defaults_to_en_for_unsupported_language(self):
        with patch("pipeline.translator.detect", return_value="fr"):
            from pipeline.translator import detect_language
            assert detect_language("Ceci est un texte suffisamment long pour le test") == "en"

    def test_returns_en_on_exception(self):
        from langdetect import LangDetectException
        with patch("pipeline.translator.detect", side_effect=LangDetectException(0, "")):
            from pipeline.translator import detect_language
            assert detect_language("This is a long enough sentence for detection") == "en"

    def test_normalises_singlish_to_en(self):
        with patch("pipeline.translator.detect", return_value="en-sg"):
            from pipeline.translator import detect_language
            assert detect_language("Wah this one very good leh cannot make it") == "en"


class TestTranslateToEnglish:
    @pytest.mark.asyncio
    async def test_returns_original_on_api_failure(self):
        with patch("pipeline.translator._call_sealion_translate", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "original text"

            from pipeline.translator import translate_to_english
            result = await translate_to_english("original text", "zh")
            assert result == "original text"

    @pytest.mark.asyncio
    async def test_returns_unchanged_for_english(self):
        from pipeline.translator import translate_to_english
        result = await translate_to_english("Hello world", "en")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_backward_compatible_signature(self):
        with patch("pipeline.translator._call_sealion_translate", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "Hello"

            from pipeline.translator import translate_to_english
            result = await translate_to_english(
                "你好",
                "zh",
                runner=MagicMock(),
                user_id="u1",
                session_id="s1",
            )
            assert result == "Hello"


class TestTranslateFromEnglish:
    @pytest.mark.asyncio
    async def test_returns_english_on_failure(self):
        with patch("pipeline.translator._call_sealion_translate", new_callable=AsyncMock) as mock:
            mock.return_value = "English explanation"

            from pipeline.translator import translate_from_english
            result = await translate_from_english("English explanation", "zh")
            assert result == "English explanation"

    @pytest.mark.asyncio
    async def test_returns_unchanged_for_english(self):
        from pipeline.translator import translate_from_english
        result = await translate_from_english("Hello world", "en")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_backward_compatible_signature(self):
        with patch("pipeline.translator._call_sealion_translate", new_callable=AsyncMock) as mock:
            mock.return_value = "你好"

            from pipeline.translator import translate_from_english
            result = await translate_from_english(
                "Hello",
                "zh",
                runner=MagicMock(),
                user_id="u1",
                session_id="s1",
            )
            assert result == "你好"

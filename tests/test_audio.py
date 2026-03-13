"""Tests for media/audio.py — transcribe_audio() and synthesise_speech()."""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestTranscribeAudio:
    @pytest.mark.asyncio
    async def test_returns_correct_shape_on_success(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"fake audio data" * 100)

        mock_alt = MagicMock()
        mock_alt.transcript = "Hello world"
        mock_alt.confidence = 0.95

        mock_channel = MagicMock()
        mock_channel.alternatives = [mock_alt]
        mock_channel.detected_language = "en"

        mock_result = MagicMock()
        mock_result.channels = [mock_channel]

        mock_metadata = MagicMock()
        mock_metadata.duration = 5.0

        mock_response = MagicMock()
        mock_response.results = mock_result
        mock_response.metadata = mock_metadata

        with patch("media.audio.DEEPGRAM_API_KEY", "fake-key"), \
             patch("deepgram.DeepgramClient") as mock_dg:
            mock_client = MagicMock()
            mock_client.listen.v1.media.transcribe_file.return_value = mock_response
            mock_dg.return_value = mock_client

            from media.audio import transcribe_audio
            result = await transcribe_audio(str(audio_file))

            assert result["transcript"] == "Hello world"
            assert result["detected_language"] == "en"
            assert result["confidence"] == 0.95
            assert result["duration_seconds"] == 5.0

    @pytest.mark.asyncio
    async def test_returns_empty_on_sdk_exception(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"data" * 100)

        with patch("media.audio.DEEPGRAM_API_KEY", "fake-key"), \
             patch("deepgram.DeepgramClient", side_effect=RuntimeError("SDK error")):
            from media.audio import transcribe_audio
            result = await transcribe_audio(str(audio_file))
            assert result["transcript"] == ""

    @pytest.mark.asyncio
    async def test_rejects_files_over_25mb(self, tmp_path):
        audio_file = tmp_path / "big.ogg"
        # Create a file that reports > 25MB
        audio_file.write_bytes(b"x")

        with patch("os.path.getsize", return_value=26 * 1024 * 1024):
            from media.audio import transcribe_audio
            result = await transcribe_audio(str(audio_file))
            assert result["transcript"] == ""

    @pytest.mark.asyncio
    async def test_uses_deepgram_detected_language(self, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"data" * 100)

        mock_alt = MagicMock()
        mock_alt.transcript = "你好世界"
        mock_alt.confidence = 0.90

        mock_channel = MagicMock()
        mock_channel.alternatives = [mock_alt]
        mock_channel.detected_language = "zh"

        mock_result = MagicMock()
        mock_result.channels = [mock_channel]

        mock_response = MagicMock()
        mock_response.results = mock_result
        mock_response.metadata = MagicMock(duration=3.0)

        with patch("media.audio.DEEPGRAM_API_KEY", "fake-key"), \
             patch("deepgram.DeepgramClient") as mock_dg:
            mock_client = MagicMock()
            mock_client.listen.v1.media.transcribe_file.return_value = mock_response
            mock_dg.return_value = mock_client

            from media.audio import transcribe_audio
            result = await transcribe_audio(str(audio_file))
            assert result["detected_language"] == "zh"


class TestSynthesiseSpeech:
    @pytest.mark.asyncio
    async def test_returns_output_path_on_success(self, tmp_path):
        output_path = str(tmp_path / "output.mp3")

        with patch("media.audio.ELEVENLABS_API_KEY", "fake-key"), \
             patch("media.audio.ELEVENLABS_VOICE_ID", "fake-voice"), \
             patch("elevenlabs.ElevenLabs") as mock_el:
            mock_client = MagicMock()
            mock_client.text_to_speech.convert.return_value = [b"audio data"]
            mock_el.return_value = mock_client

            from media.audio import synthesise_speech
            result = await synthesise_speech("Hello world, this is a test sentence.", output_path)
            assert result == output_path

    @pytest.mark.asyncio
    async def test_returns_empty_on_sdk_exception(self, tmp_path):
        output_path = str(tmp_path / "output.mp3")

        with patch("media.audio.ELEVENLABS_API_KEY", "fake-key"), \
             patch("media.audio.ELEVENLABS_VOICE_ID", "fake-voice"), \
             patch("elevenlabs.ElevenLabs", side_effect=RuntimeError("SDK error")):
            from media.audio import synthesise_speech
            result = await synthesise_speech("Hello world, this is a test.", output_path)
            assert result == ""

    @pytest.mark.asyncio
    async def test_does_not_call_api_for_short_text(self):
        with patch("elevenlabs.ElevenLabs") as mock_el:
            from media.audio import synthesise_speech
            result = await synthesise_speech("Hi", "/tmp/out.mp3")
            assert result == ""
            mock_el.assert_not_called()

    @pytest.mark.asyncio
    async def test_truncates_text_at_500_chars(self, tmp_path):
        output_path = str(tmp_path / "output.mp3")
        long_text = "A" * 1000

        with patch("media.audio.ELEVENLABS_API_KEY", "fake-key"), \
             patch("media.audio.ELEVENLABS_VOICE_ID", "fake-voice"), \
             patch("elevenlabs.ElevenLabs") as mock_el:
            mock_client = MagicMock()
            mock_client.text_to_speech.convert.return_value = [b"audio"]
            mock_el.return_value = mock_client

            from media.audio import synthesise_speech
            await synthesise_speech(long_text, output_path)

            call_args = mock_client.text_to_speech.convert.call_args
            assert len(call_args.kwargs.get("text", call_args[1].get("text", ""))) <= 500

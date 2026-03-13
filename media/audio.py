"""
media/audio.py — Deepgram STT + ElevenLabs TTS.
"""

import asyncio
import logging
import os
import re

from config import DEEPGRAM_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID

logger = logging.getLogger(__name__)

MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25 MB


async def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe audio file using Deepgram Nova-2.

    Returns:
        dict: transcript (str), detected_language (str),
              confidence (float), duration_seconds (float).

    On failure: returns fallback dict with empty transcript.
    """
    _fallback = {
        "transcript": "",
        "detected_language": "en",
        "confidence": 0.0,
        "duration_seconds": 0.0,
    }

    # Check file size
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_AUDIO_SIZE:
            logger.warning("[Audio] File too large: %d bytes", file_size)
            return _fallback
    except OSError:
        return _fallback

    if not DEEPGRAM_API_KEY:
        logger.warning("[Audio] DEEPGRAM_API_KEY not set")
        return _fallback

    try:
        from deepgram import DeepgramClient

        client = DeepgramClient(api_key=DEEPGRAM_API_KEY)

        with open(file_path, "rb") as f:
            buffer_data = f.read()

        response = await asyncio.to_thread(
            client.listen.v1.media.transcribe_file,
            request=buffer_data,
            model="nova-2-general",
            smart_format=True,
            detect_language=True,
            punctuate=True,
        )

        result = response.results
        channel = result.channels[0]
        alt = channel.alternatives[0]

        transcript = alt.transcript or ""
        confidence = alt.confidence or 0.0
        detected_lang = channel.detected_language or "en"
        duration = response.metadata.duration if hasattr(response, "metadata") else 0.0

        return {
            "transcript": transcript,
            "detected_language": detected_lang,
            "confidence": confidence,
            "duration_seconds": duration,
        }
    except Exception as e:
        logger.exception("[Audio] Deepgram transcription failed: %s", e)
        return _fallback


async def synthesise_speech(
    text: str, output_path: str, language: str = "en"
) -> str:
    """
    Generate voice note using ElevenLabs eleven_multilingual_v2.

    Args:
        text: Text to synthesise (truncated to 500 chars if longer).
        output_path: Where to save the .mp3 file.
        language: ISO 639-1 code — passed as hint to ElevenLabs.

    Returns:
        output_path on success, "" on failure.
    """
    if not text or len(text) < 10:
        return ""

    if not ELEVENLABS_API_KEY or not ELEVENLABS_VOICE_ID:
        logger.warning("[TTS] ElevenLabs credentials not set")
        return ""

    # Strip HTML tags and truncate
    text = re.sub(r"<[^>]+>", "", text)
    text = text[:500]

    try:
        from elevenlabs import ElevenLabs

        client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
        audio = await asyncio.to_thread(
            client.text_to_speech.convert,
            text=text,
            voice_id=ELEVENLABS_VOICE_ID,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )

        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

        return output_path
    except Exception as e:
        logger.exception("[TTS] ElevenLabs synthesis failed: %s", e)
        return ""

"""
media/live.py — Gemini Live API: bidirectional audio (STT + TTS in one WebSocket).

Primary audio path for SENTINEL. Replaces ElevenLabs TTS for voice replies.
Falls back gracefully to b"" on any failure — never raises into the caller.
"""

import io
import logging

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_LIVE_VOICE

logger = logging.getLogger(__name__)

SENTINEL_LIVE_PERSONA = """
You are SENTINEL, an AI content detection assistant for Singapore users.
You have just analysed the user's audio and detected the following:

{detection_context}

In 2–3 spoken sentences:
1. State clearly what was found (AI-generated or genuine)
2. Explain the key signal or reason
3. Give one practical recommendation

Speak naturally. Be concise — under 20 seconds. Avoid jargon.
Supported languages: English, Mandarin, Malay, Tamil, Singlish.
"""


async def live_voice_exchange(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    system_context: str = "",
) -> bytes:
    """
    Send audio to Gemini Live API. Returns OGG audio bytes ready for Telegram.
    Falls back to empty bytes on any failure — never raises.

    Args:
        audio_bytes: Raw audio from Telegram voice note.
        mime_type:   MIME type of input audio (audio/ogg, audio/mp4, audio/wav).
        system_context: Optional detection context injected into the session
                        (e.g. GUARD verdict, misinfo result) so the spoken
                        verdict is informed by the detection pipeline.
    Returns:
        OGG audio bytes ready to send as Telegram voice note.
        Returns b"" on failure.
    """
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        # Convert input audio to PCM16 mono 16kHz — the only format Live API accepts
        pcm_input = _to_pcm(audio_bytes, mime_type)
        if not pcm_input:
            logger.warning("[Live API] Could not convert input audio to PCM")
            return b""

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=GEMINI_LIVE_VOICE
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[
                    types.Part(
                        text=SENTINEL_LIVE_PERSONA.format(
                            detection_context=system_context
                            or "No prior detection context."
                        )
                    )
                ]
            ),
        )

        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        ) as session:
            await session.send_realtime_input(
                audio=types.Blob(data=pcm_input, mime_type="audio/pcm;rate=16000")
            )
            await session.send_client_content(
                turns=types.Content(
                    parts=[types.Part(text=".")]
                ),
                turn_complete=True,
            )

            pcm_audio = b""
            async for message in session.receive():
                if (
                    message.server_content
                    and message.server_content.model_turn
                ):
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data:
                            pcm_audio += part.inline_data.data

        return _pcm_to_ogg(pcm_audio)

    except Exception as e:
        logger.warning("[Live API] Failed: %s — falling back to ElevenLabs", e)
        return b""


def _pcm_to_ogg(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Convert raw PCM16 from Gemini Live API to OGG/Vorbis for Telegram."""
    if not pcm_bytes:
        return b""
    try:
        from pydub import AudioSegment

        audio = AudioSegment(
            data=pcm_bytes,
            sample_width=2,
            frame_rate=sample_rate,
            channels=1,
        )
        buf = io.BytesIO()
        audio.export(buf, format="ogg", codec="libvorbis")
        return buf.getvalue()
    except Exception as e:
        logger.error("[Live API] PCM→OGG conversion failed: %s", e)
        return b""


def _to_pcm(audio_bytes: bytes, mime_type: str) -> bytes:
    """Convert any input audio format to PCM16 mono 16kHz for the Live API."""
    try:
        from pydub import AudioSegment

        fmt_map = {
            "audio/ogg": "ogg",
            "audio/mp4": "mp4",
            "audio/mpeg": "mp3",
            "audio/wav": "wav",
            "audio/webm": "webm",
        }
        fmt = fmt_map.get(mime_type, "ogg")
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        return audio.raw_data
    except Exception as e:
        logger.error("[Live API] Input audio conversion failed: %s", e)
        return b""

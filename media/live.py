"""
media/live.py — Gemini Live API: bidirectional audio (STT + TTS in one WebSocket).

Primary audio path for SENTINEL. Replaces ElevenLabs TTS for voice replies.
Falls back gracefully to b"" on any failure — never raises into the caller.

Supports two modes:
1. live_voice_exchange() — batch: send audio → receive spoken verdict (Telegram)
2. InterruptibleLiveSession — streaming: real-time send/receive with
   interruption support (WebSocket dashboard)
"""

import asyncio
import io
import logging
import os
import shutil
import subprocess
import tempfile
from typing import AsyncGenerator

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_LIVE_VOICE, GOOGLE_GENAI_USE_VERTEXAI

logger = logging.getLogger(__name__)

# 100ms of PCM16 mono 16kHz = 3200 bytes per chunk
_CHUNK_SIZE = 3200
_CHUNK_INTERVAL = 0.1

# Cache ffmpeg availability check
_ffmpeg_path: str | None = shutil.which("ffmpeg")

# Container formats that require a seekable input — pipe:0 won't work for these.
_SEEKABLE_FORMATS: frozenset[str] = frozenset({"mp4", "webm"})


def _make_genai_client() -> genai.Client:
    """Create a Gemini client using Vertex AI (ADC) or API key depending on config."""
    if GOOGLE_GENAI_USE_VERTEXAI:
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("GOOGLE_CLOUD_REGION")
        if not project or not location:
            logger.error(
                "Vertex AI mode enabled (GOOGLE_GENAI_USE_VERTEXAI=True) but "
                "GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_LOCATION/GOOGLE_CLOUD_REGION is not set."
            )
            raise RuntimeError(
                "Missing GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_LOCATION/GOOGLE_CLOUD_REGION for Vertex AI client."
            )
        return genai.Client(vertexai=True, project=project, location=location)

    if not GEMINI_API_KEY:
        logger.error(
            "GOOGLE_GENAI_USE_VERTEXAI is False but GEMINI_API_KEY is not configured."
        )
        raise RuntimeError("GEMINI_API_KEY must be set when not using Vertex AI.")

    return genai.Client(api_key=GEMINI_API_KEY)


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
        client = _make_genai_client()

        # Convert input audio to PCM16 mono 16kHz — the only format Live API accepts
        pcm_input = _to_pcm(audio_bytes, mime_type)
        if not pcm_input:
            logger.warning("[Live API] Could not convert input audio to PCM")
            return b""

        config = _build_live_config(system_context)

        logger.info("[Live API] Session opened — model=%s", GEMINI_LIVE_MODEL)

        async with client.aio.live.connect(
            model=GEMINI_LIVE_MODEL,
            config=config,
        ) as session:
            # Stream audio in chunks to enable real-time processing
            for i in range(0, len(pcm_input), _CHUNK_SIZE):
                chunk = pcm_input[i : i + _CHUNK_SIZE]
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk, mime_type="audio/pcm;rate=16000"
                    )
                )
                await asyncio.sleep(_CHUNK_INTERVAL)

            await session.send_client_content(
                turns=types.Content(
                    parts=[types.Part(text=".")]
                ),
                turn_complete=True,
            )

            pcm_audio = b""
            async for message in session.receive():
                if not message.server_content:
                    continue
                if message.server_content.interrupted:
                    logger.info("[Live API] Model turn interrupted")
                    break
                if message.server_content.model_turn:
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data:
                            pcm_audio += part.inline_data.data
                if message.server_content.turn_complete:
                    break

        logger.info("[Live API] Received %d bytes PCM audio", len(pcm_audio))

        ogg_audio = _pcm_to_ogg(pcm_audio)
        if ogg_audio:
            logger.info(
                "[Live API] Converted to %d bytes OGG — sending reply",
                len(ogg_audio),
            )
        return ogg_audio

    except Exception as e:
        logger.warning("[Live API] Failed: %s — falling back to ElevenLabs", e)
        return b""


def _pcm_to_ogg(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """Convert raw PCM16 from Gemini Live API to OGG/Vorbis for Telegram.

    Uses subprocess ffmpeg directly to avoid the pydub ``audioop`` dependency
    that was removed in Python 3.13+.  Falls back to pydub if ffmpeg is not
    on PATH.
    """
    if not pcm_bytes:
        return b""

    # Primary: subprocess ffmpeg (no audioop needed)
    if _ffmpeg_path:
        try:
            result = subprocess.run(
                [
                    _ffmpeg_path, "-y",
                    "-f", "s16le", "-ar", str(sample_rate), "-ac", "1",
                    "-i", "pipe:0",
                    "-c:a", "libvorbis", "-f", "ogg", "pipe:1",
                ],
                input=pcm_bytes,
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
            logger.warning(
                "[Live API] ffmpeg PCM→OGG returned %d: %s",
                result.returncode,
                result.stderr[:200] if result.stderr else "",
            )
        except Exception as e:
            logger.warning("[Live API] ffmpeg PCM→OGG failed: %s", e)

    # Fallback: pydub (requires audioop + ffmpeg)
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
    """Convert any input audio format to PCM16 mono 16kHz for the Live API.

    Uses subprocess ffmpeg directly to avoid the pydub ``audioop`` dependency
    that was removed in Python 3.13+.  Falls back to pydub if ffmpeg is not
    on PATH.
    """
    if not audio_bytes:
        return b""

    fmt_map = {
        "audio/ogg": "ogg",
        "audio/mp4": "mp4",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/webm": "webm",
    }
    fmt = fmt_map.get(mime_type, "ogg")

    # Primary: subprocess ffmpeg (no audioop needed)
    if _ffmpeg_path:
        try:
            if fmt in _SEEKABLE_FORMATS:
                # Write to a temp file so ffmpeg can seek through the container.
                tmp_fd, tmp_path = tempfile.mkstemp(suffix=f".{fmt}")
                try:
                    try:
                        os.write(tmp_fd, audio_bytes)
                    finally:
                        os.close(tmp_fd)
                    result = subprocess.run(
                        [
                            _ffmpeg_path, "-y",
                            "-i", tmp_path,
                            "-f", "s16le", "-ar", "16000", "-ac", "1", "pipe:1",
                        ],
                        capture_output=True,
                        timeout=30,
                    )
                finally:
                    os.unlink(tmp_path)
            else:
                result = subprocess.run(
                    [
                        _ffmpeg_path, "-y",
                        "-f", fmt, "-i", "pipe:0",
                        "-f", "s16le", "-ar", "16000", "-ac", "1", "pipe:1",
                    ],
                    input=audio_bytes,
                    capture_output=True,
                    timeout=30,
                )
            if result.returncode == 0 and result.stdout:
                return result.stdout
            logger.warning(
                "[Live API] ffmpeg input conversion returned %d: %s",
                result.returncode,
                result.stderr[:200] if result.stderr else "",
            )
        except Exception as e:
            logger.warning("[Live API] ffmpeg input conversion failed: %s", e)

    # Fallback: pydub (requires audioop + ffmpeg)
    try:
        from pydub import AudioSegment

        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format=fmt)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        return audio.raw_data
    except Exception as e:
        logger.error("[Live API] Input audio conversion failed: %s", e)
        return b""


# ---------------------------------------------------------------------------
# InterruptibleLiveSession — real-time streaming with interruption support
# ---------------------------------------------------------------------------


def _build_live_config(system_context: str = "") -> types.LiveConnectConfig:
    """Build a LiveConnectConfig shared by batch and streaming modes."""
    return types.LiveConnectConfig(
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


class InterruptibleLiveSession:
    """Gemini Live API session with real-time interruption support.

    Designed for the WebSocket dashboard where audio chunks arrive
    continuously and the user can interrupt the model mid-response
    by speaking again.

    Usage::

        async with InterruptibleLiveSession(system_context="...") as session:
            # Send audio chunks as they arrive from the mic
            await session.send_audio(pcm_chunk)

            # Signal user finished speaking
            await session.end_turn()

            # Stream response audio back to the client
            async for audio_chunk in session.receive_audio():
                ws.send_bytes(audio_chunk)

            # User speaks again → model is interrupted automatically
            await session.send_audio(new_pcm_chunk)
    """

    def __init__(self, system_context: str = "") -> None:
        self._system_context = system_context
        self._session: object | None = None
        self._ctx: object | None = None
        self._client: genai.Client | None = None
        self._response_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._receive_task: asyncio.Task | None = None
        self._closed = False
        self._model_speaking = False

    async def __aenter__(self) -> "InterruptibleLiveSession":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the WebSocket connection and start the background receiver."""
        self._client = _make_genai_client()
        config = _build_live_config(self._system_context)
        self._ctx = self._client.aio.live.connect(
            model=GEMINI_LIVE_MODEL, config=config
        )
        self._session = await self._ctx.__aenter__()
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info(
            "[Live API] Interruptible session opened — model=%s",
            GEMINI_LIVE_MODEL,
        )

    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Send a PCM16 audio chunk. Interrupts the model if it is speaking."""
        if self._closed or not self._session:
            return
        try:
            if self._model_speaking:
                await self.interrupt()
            await self._session.send_realtime_input(
                audio=types.Blob(
                    data=pcm_chunk, mime_type="audio/pcm;rate=16000"
                )
            )
        except Exception as e:
            logger.warning("[Live API] send_audio failed: %s", e)

    async def send_text(self, text: str) -> None:
        """Send a text message to the model."""
        if self._closed or not self._session:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(parts=[types.Part(text=text)]),
                turn_complete=True,
            )
        except Exception as e:
            logger.warning("[Live API] send_text failed: %s", e)

    async def send_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> None:
        """Send an image to the model for analysis."""
        if self._closed or not self._session:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(
                    parts=[
                        types.Part(
                            inline_data=types.Blob(
                                data=image_bytes, mime_type=mime_type
                            )
                        ),
                        types.Part(
                            text="Analyse this image for signs of AI generation or manipulation."
                        ),
                    ]
                ),
                turn_complete=True,
            )
        except Exception as e:
            logger.warning("[Live API] send_image failed: %s", e)

    async def end_turn(self) -> None:
        """Signal that the user has finished speaking."""
        if self._closed or not self._session:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(parts=[types.Part(text=".")]),
                turn_complete=True,
            )
        except Exception as e:
            logger.warning("[Live API] end_turn failed: %s", e)

    async def interrupt(self) -> None:
        """Signal barge-in — stop current model turn."""
        if self._closed or not self._session:
            return
        try:
            await self._session.send_client_content(
                turns=types.Content(parts=[types.Part(text=".")]),
                turn_complete=True,
            )
            self._model_speaking = False
            await self._response_queue.put(None)
        except Exception as e:
            logger.warning("[Live API] interrupt() failed: %s", e)

    async def receive_audio(self) -> AsyncGenerator[bytes, None]:
        """Yield PCM16 audio chunks as the model speaks.

        Terminates when the model finishes its turn or is interrupted.
        Can be called again for the next turn.
        """
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._response_queue.get(), timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("[Live API] receive_audio timed out")
                return
            if chunk is None:
                return
            yield chunk

    @property
    def is_model_speaking(self) -> bool:
        """True while the model is actively generating audio."""
        return self._model_speaking

    async def _receive_loop(self) -> None:
        """Background task reading from the Live API WebSocket."""
        try:
            async for message in self._session.receive():
                if self._closed:
                    break
                if not message.server_content:
                    continue

                # Interruption: user sent new audio while model was speaking
                if message.server_content.interrupted:
                    logger.info("[Live API] Model interrupted by user")
                    self._model_speaking = False
                    await self._response_queue.put(None)
                    continue

                if message.server_content.model_turn:
                    self._model_speaking = True
                    for part in message.server_content.model_turn.parts:
                        if part.inline_data:
                            await self._response_queue.put(
                                part.inline_data.data
                            )

                if message.server_content.turn_complete:
                    self._model_speaking = False
                    await self._response_queue.put(None)
        except Exception as e:
            if not self._closed:
                logger.warning("[Live API] receive_loop error: %s", e)
        finally:
            self._model_speaking = False
            await self._response_queue.put(None)

    async def close(self) -> None:
        """Close the session and cancel the background receiver."""
        if self._closed:
            return
        self._closed = True
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except (asyncio.CancelledError, Exception):
                pass
        if self._ctx:
            try:
                await self._ctx.__aexit__(None, None, None)
            except Exception:
                pass
        logger.info("[Live API] Interruptible session closed")

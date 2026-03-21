"""
tests/test_live.py — Unit tests for media/live.py (Gemini Live API).

All external API calls are mocked — no real WebSockets are opened.
"""

import asyncio
import io
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from media.live import InterruptibleLiveSession, live_voice_exchange, _pcm_to_ogg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_iter(items):
    for item in items:
        yield item


def _make_mock_session(pcm_data: bytes):
    """Return a mock session that yields a single audio message then turn_complete."""
    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = pcm_data

    audio_msg = MagicMock()
    audio_msg.server_content = MagicMock()
    audio_msg.server_content.model_turn = MagicMock()
    audio_msg.server_content.model_turn.parts = [part]
    audio_msg.server_content.interrupted = False
    audio_msg.server_content.turn_complete = False

    end_msg = MagicMock()
    end_msg.server_content = MagicMock()
    end_msg.server_content.model_turn = None
    end_msg.server_content.interrupted = False
    end_msg.server_content.turn_complete = True

    session = AsyncMock()
    session.receive = MagicMock(return_value=_async_iter([audio_msg, end_msg]))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


# ---------------------------------------------------------------------------
# live_voice_exchange — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_voice_exchange_returns_bytes_on_success():
    """Live API returns OGG bytes when Gemini responds with PCM audio."""
    pcm_data = b"\x00\x01" * 2400  # 2400 samples of silence at 24kHz
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")

    session = _make_mock_session(pcm_data)

    with patch("media.live.genai.Client") as mock_client_cls, \
         patch("media.live._to_pcm", return_value=b"\x00\x00" * 1600), \
         patch("media.live._ffmpeg_path", ffmpeg):
        mock_client_cls.return_value.aio.live.connect.return_value = session

        result = await live_voice_exchange(b"fake_audio_bytes")

    assert isinstance(result, bytes)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_live_voice_exchange_passes_system_context():
    """system_context is injected into the Live API system instruction."""
    session = _make_mock_session(b"\x00\x01" * 100)

    with patch("media.live.genai.Client") as mock_client_cls, \
         patch("media.live._to_pcm", return_value=b"\x00\x00" * 1600):
        mock_client_cls.return_value.aio.live.connect.return_value = session

        await live_voice_exchange(
            b"audio",
            system_context="GUARD verdict: AI-generated (0.95)",
        )

    # Verify connect() was called with a config containing system_instruction
    connect_call = mock_client_cls.return_value.aio.live.connect
    assert connect_call.called
    call_kwargs = connect_call.call_args
    config = call_kwargs.kwargs.get("config") or call_kwargs.args[1]
    instruction_text = config.system_instruction.parts[0].text
    assert "AI-generated (0.95)" in instruction_text


# ---------------------------------------------------------------------------
# live_voice_exchange — failure / fallback path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_voice_exchange_returns_empty_bytes_on_api_error():
    """Returns b'' when Gemini Live API raises an exception — never re-raises."""
    with patch("media.live.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.aio.live.connect.side_effect = Exception(
            "API unavailable"
        )

        result = await live_voice_exchange(b"fake_audio_bytes")

    assert result == b""


@pytest.mark.asyncio
async def test_live_voice_exchange_returns_empty_bytes_on_empty_pcm():
    """Returns b'' when the model sends back no audio data."""
    message = MagicMock()
    message.server_content = MagicMock()
    message.server_content.model_turn = MagicMock()
    message.server_content.model_turn.parts = []
    message.server_content.interrupted = False
    message.server_content.turn_complete = True

    session = AsyncMock()
    session.receive = MagicMock(return_value=_async_iter([message]))
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    with patch("media.live.genai.Client") as mock_client_cls:
        mock_client_cls.return_value.aio.live.connect.return_value = session

        result = await live_voice_exchange(b"fake_audio_bytes")

    assert result == b""


# ---------------------------------------------------------------------------
# _pcm_to_ogg — unit tests
# ---------------------------------------------------------------------------

def test_pcm_to_ogg_returns_empty_bytes_for_empty_input():
    assert _pcm_to_ogg(b"") == b""


def test_pcm_to_ogg_returns_ogg_bytes_for_valid_pcm():
    # 0.1 s of silence: 24000 samples/s × 0.1 × 2 bytes/sample = 4800 bytes
    silent_pcm = b"\x00\x00" * 2400
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg not installed")
    with patch("media.live._ffmpeg_path", ffmpeg):
        result = _pcm_to_ogg(silent_pcm)
    assert isinstance(result, bytes)
    assert len(result) > 0
    # OGG files start with "OggS" magic bytes
    assert result[:4] == b"OggS"


def test_pcm_to_ogg_returns_empty_bytes_on_pydub_error():
    with patch("media.live._ffmpeg_path", None), \
         patch("media.live.io.BytesIO", side_effect=Exception("pydub error")):
        result = _pcm_to_ogg(b"\x00\x01" * 100)
    assert result == b""


# ---------------------------------------------------------------------------
# InterruptibleLiveSession.interrupt() — focused unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interrupt_unblocks_receive_audio_and_does_not_leak_subsequent_chunks():
    """interrupt() must:
    - unblock a receive_audio() call that is waiting for more data
    - return only the chunks that were enqueued before the interrupt sentinel
    - not yield any chunk enqueued after interrupt() is called
    """
    ils = InterruptibleLiveSession(system_context="test")

    # Inject a mock live session so interrupt() can call send_client_content
    mock_live_session = AsyncMock()
    ils._session = mock_live_session
    ils._model_speaking = True

    # Pre-interrupt audio chunks
    chunk_before_1 = b"\x10\x11" * 100
    chunk_before_2 = b"\x20\x21" * 100
    # Post-interrupt audio chunk — must never appear in the output
    chunk_after = b"\x30\x31" * 100

    # Enqueue the two pre-interrupt chunks as if the model was already speaking
    await ils._response_queue.put(chunk_before_1)
    await ils._response_queue.put(chunk_before_2)

    received: list[bytes] = []
    pre_interrupt_drained = asyncio.Event()

    async def _collect() -> None:
        async for chunk in ils.receive_audio():
            received.append(chunk)
            # Once both pre-interrupt chunks have been consumed, signal the test
            if len(received) == 2:
                pre_interrupt_drained.set()

    # Start draining the queue in the background
    collect_task = asyncio.create_task(_collect())

    # Wait deterministically until both pre-interrupt chunks have been
    # consumed so we can be sure the consumer is now blocked waiting for
    # the next item before we call interrupt().
    await asyncio.wait_for(pre_interrupt_drained.wait(), timeout=1.0)

    # Interrupt — this sets _model_speaking=False and enqueues None
    await ils.interrupt()

    # Enqueue a chunk that arrives after the interrupt; it must not be yielded
    await ils._response_queue.put(chunk_after)

    await asyncio.wait_for(collect_task, timeout=2.0)

    # We must receive exactly the two pre-interrupt chunks, in order, and nothing else.
    assert received == [chunk_before_1, chunk_before_2], (
        "receive_audio() must yield exactly the two pre-interrupt chunks in order"
    )
    assert not ils.is_model_speaking, "_model_speaking should be False after interrupt"


@pytest.mark.asyncio
async def test_interrupt_sets_model_speaking_false():
    """interrupt() must clear the is_model_speaking flag."""
    ils = InterruptibleLiveSession(system_context="test")
    mock_live_session = AsyncMock()
    ils._session = mock_live_session
    ils._model_speaking = True

    await ils.interrupt()

    assert not ils.is_model_speaking


@pytest.mark.asyncio
async def test_interrupt_while_session_closed_is_a_noop():
    """interrupt() on a closed session must not raise and must not enqueue anything."""
    ils = InterruptibleLiveSession(system_context="test")
    ils._closed = True
    ils._session = AsyncMock()

    await ils.interrupt()  # must not raise

    assert ils._response_queue.empty()

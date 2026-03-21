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

    # Inject a non-None live session so interrupt() does not early-return when _session is None
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

    try:
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
    finally:
        if not collect_task.done():
            collect_task.cancel()
            try:
                await collect_task
            except asyncio.CancelledError:
                pass


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
    mock_live_session = AsyncMock()
    ils._session = mock_live_session

    await ils.interrupt()  # must not raise

    assert ils._response_queue.empty()
    mock_live_session.send_client_content.assert_not_called()
# InterruptibleLiveSession — interrupt() correctness
# ---------------------------------------------------------------------------

async def _never_ending_receive():
    """Async generator that suspends indefinitely — simulates an open, idle WebSocket.

    Keeps ``_receive_loop()`` suspended at ``await aiter.__anext__()`` until the
    background task is cancelled by ``close()``, so queue-state assertions made
    after ``interrupt()`` are deterministic (no race with the finally-block sentinel).
    """
    await asyncio.Event().wait()  # suspends until CancelledError is injected by close()
    yield  # pragma: no cover — unreachable; required to make this an async generator


def _make_interruptible_session_mock():
    """Return a mock genai.Client whose live.connect() is an async context manager.

    The returned session's receive() method yields from a gated async iterator
    that keeps the receive loop alive until the session is explicitly closed.
    This avoids timing-dependent completion of the background _receive_loop()
    during tests that assert on the response queue after interrupt().
    """
    mock_session = AsyncMock()

    gate = asyncio.Event()

    async def _receive_iter():
        # Keep the iterator (and thus the receive loop) alive until the gate is set.
        try:
            await gate.wait()
        finally:
            # Once the gate is set, allow the iterator to complete so that the
            # production receive loop can run its finally block.
            return
        # Unreachable yield to ensure this is treated as an async generator.
        if False:  # pragma: no cover - defensive; never executed.
            yield None

    mock_session.receive = MagicMock(return_value=_receive_iter())

    async def _signal_close(*args, **kwargs):
        gate.set()

    # Ensure that closing the session signals the iterator to finish.
    mock_session.close = AsyncMock(side_effect=_signal_close)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)

    async def _aexit(*args, **kwargs):
        gate.set()
        return False

    mock_ctx.__aexit__ = AsyncMock(side_effect=_aexit)
    mock_client = MagicMock()
    mock_client.aio.live.connect.return_value = mock_ctx
    return mock_client, mock_session


@pytest.mark.asyncio
async def test_interrupt_drains_queued_audio():
    """interrupt() removes already-enqueued audio chunks from the queue."""
    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, _ = _make_interruptible_session_mock()
        mock_factory.return_value = mock_client

        session = InterruptibleLiveSession()
        await session.connect()

        # Pre-populate the queue with three audio chunks
        for i in range(3):
            await session._response_queue.put(bytes([i]) * 100)

        await session.interrupt()

        # After interrupt() the queue should contain only the None sentinel
        assert session._response_queue.qsize() == 1
        sentinel = session._response_queue.get_nowait()
        assert sentinel is None

        await session.close()


@pytest.mark.asyncio
async def test_interrupt_increments_generation():
    """interrupt() increments _generation to invalidate in-flight audio."""
    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, _ = _make_interruptible_session_mock()
        mock_factory.return_value = mock_client

        session = InterruptibleLiveSession()
        await session.connect()

        assert session._generation == 0
        await session.interrupt()
        assert session._generation == 1
        await session.interrupt()
        assert session._generation == 2

        await session.close()


@pytest.mark.asyncio
async def test_receive_loop_discards_audio_after_interrupt():
    """Audio that arrives from the server after interrupt() is discarded.

    The receive_loop captures ``gen`` before awaiting the next message.
    We use a gate to ensure the generation is incremented *while* the loop
    is suspended waiting for the message, so when the message finally arrives
    ``gen != self._generation`` and the audio is discarded.
    """
    pcm_chunk = b"\xAB" * 200

    audio_part = MagicMock()
    audio_part.inline_data = MagicMock()
    audio_part.inline_data.data = pcm_chunk

    audio_msg = MagicMock()
    audio_msg.server_content = MagicMock()
    audio_msg.server_content.model_turn = MagicMock()
    audio_msg.server_content.model_turn.parts = [audio_part]
    audio_msg.server_content.interrupted = False
    audio_msg.server_content.turn_complete = False

    # Gate: holds back the message until after interrupt() increments generation.
    gate = asyncio.Event()

    async def gated_receive():
        await gate.wait()  # suspends, giving the test a chance to interrupt
        yield audio_msg

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Let the receive_loop start and reach the gate (gen=0 captured).
        await asyncio.sleep(0)

        # Simulate interrupt(): advance generation while loop is suspended.
        ils._generation += 1

        # Release the gate so the audio message is delivered.
        gate.set()
        await asyncio.sleep(0.05)

        # Queue should contain only the finally-block sentinel; no audio.
        items = []
        while not ils._response_queue.empty():
            items.append(ils._response_queue.get_nowait())

        audio_items = [x for x in items if x is not None]
        assert audio_items == [], (
            "Stale audio from a superseded generation must not appear in the queue"
        )

        await ils.close()


@pytest.mark.asyncio
async def test_receive_loop_omits_turn_complete_sentinel_after_interrupt():
    """turn_complete does not add a duplicate sentinel when generation changed.

    interrupt() enqueues its own sentinel; the receive_loop must not also
    enqueue one for the stale turn_complete, or the next receive_audio()
    call would terminate immediately without yielding any audio.
    """
    end_msg = MagicMock()
    end_msg.server_content = MagicMock()
    end_msg.server_content.model_turn = None
    end_msg.server_content.interrupted = False
    end_msg.server_content.turn_complete = True

    gate = asyncio.Event()

    async def gated_receive():
        await gate.wait()
        yield end_msg

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Let the receive_loop start and block at the gate (gen=0 captured).
        await asyncio.sleep(0)

        # Simulate interrupt(): advance generation and enqueue its sentinel.
        ils._generation += 1
        await ils._response_queue.put(None)  # interrupt()'s sentinel

        # Release the stale turn_complete message.
        gate.set()
        await asyncio.sleep(0.05)

        # Collect everything in the queue (including the finally sentinel).
        sentinels = []
        while not ils._response_queue.empty():
            sentinels.append(ils._response_queue.get_nowait())

        none_count = sum(1 for x in sentinels if x is None)
        # Expected: 1 from interrupt() + 1 from finally = exactly 2.
        # The stale turn_complete must NOT add a third.
        assert none_count == 2, (
            f"Expected exactly 2 None sentinels (interrupt + finally) but got {none_count}"
        )

        await ils.close()

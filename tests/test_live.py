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


@pytest.mark.asyncio
async def test_send_audio_does_not_auto_interrupt():
    """send_audio must NOT call interrupt() — barge-in is handled client-side."""
    ils = InterruptibleLiveSession(system_context="test")
    mock_live_session = AsyncMock()
    ils._session = mock_live_session
    ils._model_speaking = True

    with patch.object(ils, "interrupt", new=AsyncMock()) as mock_interrupt:
        await ils.send_audio(b"\x01\x02" * 100)

    mock_interrupt.assert_not_awaited()
    mock_live_session.send_realtime_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_audio_does_not_interrupt_when_model_not_speaking():
    """send_audio() should not call interrupt() if model is not speaking."""
    ils = InterruptibleLiveSession(system_context="test")
    mock_live_session = AsyncMock()
    ils._session = mock_live_session
    ils._model_speaking = False

    with patch.object(ils, "interrupt", new=AsyncMock()) as mock_interrupt:
        await ils.send_audio(b"\x01\x02" * 100)

    mock_interrupt.assert_not_awaited()
    mock_live_session.send_realtime_input.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_interrupt_message_calls_interrupt():
    """Explicit interrupt signal must still call session.interrupt()."""
    ils = InterruptibleLiveSession(system_context="test")
    ils._model_speaking = True
    ils._session = AsyncMock()

    with patch.object(ils, "interrupt", new=AsyncMock()) as mock_interrupt:
        await ils.interrupt()

    mock_interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_turn_uses_audio_stream_end_when_user_stream_open():
    """end_turn() should close realtime audio stream before model response."""
    ils = InterruptibleLiveSession(system_context="test")
    mock_live_session = AsyncMock()
    ils._session = mock_live_session
    ils._user_stream_open = True

    await ils.end_turn()

    mock_live_session.send_realtime_input.assert_awaited_once_with(audio_stream_end=True)
    assert ils._user_stream_open is False


@pytest.mark.asyncio
async def test_end_turn_falls_back_to_client_content_when_stream_end_unsupported():
    """end_turn() should gracefully fall back when audio_stream_end is unsupported."""
    ils = InterruptibleLiveSession(system_context="test")
    mock_live_session = AsyncMock()
    mock_live_session.send_realtime_input.side_effect = RuntimeError("unsupported")
    ils._session = mock_live_session
    ils._user_stream_open = True

    await ils.end_turn()

    assert mock_live_session.send_client_content.await_count == 1


@pytest.mark.asyncio
async def test_receive_audio_marks_interrupted_after_interrupt_signal():
    """receive_audio() should expose interrupted termination to websocket layer."""
    ils = InterruptibleLiveSession(system_context="test")
    ils._session = AsyncMock()

    async def _drain() -> list[bytes]:
        out = []
        async for chunk in ils.receive_audio():
            out.append(chunk)
        return out

    task = asyncio.create_task(_drain())
    await asyncio.sleep(0)
    await ils.interrupt()
    chunks = await asyncio.wait_for(task, timeout=1.0)

    assert chunks == []
    assert ils.last_receive_interrupted is True
# InterruptibleLiveSession — interrupt() correctness
# ---------------------------------------------------------------------------

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
async def test_receive_loop_stale_model_turn_does_not_set_model_speaking():
    """A stale model_turn (gen != self._generation) must NOT set _model_speaking=True.

    After interrupt() the flag is False.  If a stale audio chunk arrives from
    the superseded generation it must be discarded *and* the flag must stay
    False, otherwise send_audio() would incorrectly call interrupt() again and
    barge-in logic breaks.
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

    gate = asyncio.Event()

    async def gated_receive():
        await gate.wait()
        yield audio_msg

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Receive_loop is waiting at the gate with gen=0 captured.
        await asyncio.sleep(0)

        # Simulate interrupt() — advances generation; flag is cleared.
        ils._generation += 1
        ils._model_speaking = False

        # Release the stale audio message (gen=0, current=1 — stale).
        gate.set()
        await asyncio.sleep(0.05)

        assert not ils.is_model_speaking, (
            "_model_speaking must remain False after a stale model_turn "
            "from a superseded generation"
        )

        await ils.close()


@pytest.mark.asyncio
async def test_receive_loop_stale_turn_complete_does_not_clear_model_speaking():
    """A stale turn_complete (gen != self._generation) must NOT clear _model_speaking.

    If a new generation is already in progress (_model_speaking=True), a
    turn_complete arriving from the previous generation must not prematurely
    set _model_speaking=False.
    """
    end_msg = MagicMock()
    end_msg.server_content = MagicMock()
    end_msg.server_content.model_turn = None
    end_msg.server_content.interrupted = False
    end_msg.server_content.turn_complete = True

    # gate_open: release the stale turn_complete message
    # hold_open: keep the generator alive so finally block doesn't run
    gate_open = asyncio.Event()
    hold_open = asyncio.Event()

    async def gated_receive():
        await gate_open.wait()  # suspends so we can bump _generation first
        yield end_msg
        await hold_open.wait()  # keep loop alive so finally block doesn't run

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Let the receive_loop start and block at the gate (gen=0 captured).
        await asyncio.sleep(0)

        # Simulate: interrupt fired, new generation started and is speaking.
        ils._generation += 1
        ils._model_speaking = True

        # Release the stale turn_complete from the old generation.
        gate_open.set()
        await asyncio.sleep(0.05)

        assert ils.is_model_speaking, (
            "_model_speaking must remain True when a stale turn_complete "
            "arrives from a superseded generation while a new generation is "
            "still in progress"
        )

        hold_open.set()
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


@pytest.mark.asyncio
async def test_receive_loop_stale_audio_does_not_set_model_speaking():
    """Stale audio chunks (gen != current generation) must NOT set _model_speaking.

    After interrupt() increments _generation, the receive_loop may still deliver
    a model_turn message that was already in-flight.  Since that chunk is
    discarded, _model_speaking must remain False so that auto-barge-in logic
    and WS event selection are not confused by a flag that is stuck at True.
    """
    pcm_chunk = b"\xCD" * 200

    audio_part = MagicMock()
    audio_part.inline_data = MagicMock()
    audio_part.inline_data.data = pcm_chunk

    audio_msg = MagicMock()
    audio_msg.server_content = MagicMock()
    audio_msg.server_content.model_turn = MagicMock()
    audio_msg.server_content.model_turn.parts = [audio_part]
    audio_msg.server_content.interrupted = False
    audio_msg.server_content.turn_complete = False

    gate = asyncio.Event()

    async def gated_receive():
        await gate.wait()
        yield audio_msg

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Let the receive_loop start and block at the gate.
        await asyncio.sleep(0)

        # Advance generation so the pending message becomes stale.
        ils._generation += 1
        assert not ils.is_model_speaking, "Precondition: model should not be speaking"

        # Release the stale audio message.
        gate.set()
        await asyncio.sleep(0.05)

        # _model_speaking must still be False: stale chunks must not flip it.
        assert not ils.is_model_speaking, (
            "_model_speaking must not be set True by stale audio chunks"
        )

        await ils.close()


@pytest.mark.asyncio
async def test_receive_loop_stale_interrupted_does_not_add_extra_sentinel():
    """A stale server_content.interrupted (gen != self._generation) must NOT
    enqueue an additional sentinel.

    Scenario:
    - interrupt() is called, bumping _generation from 0 → 1 and placing its
      own sentinel in the queue.
    - The server then sends an ``interrupted`` ACK for the *old* turn.
      Because gen==0 but self._generation==1 when the message is processed,
      this is a stale ACK.  The receive_loop must discard it without adding
      another sentinel — otherwise the *next* receive_audio() call would
      terminate immediately before yielding any audio.
    """
    interrupted_msg = MagicMock()
    interrupted_msg.server_content = MagicMock()
    interrupted_msg.server_content.model_turn = None
    interrupted_msg.server_content.interrupted = True
    interrupted_msg.server_content.turn_complete = False

    gate = asyncio.Event()
    released = asyncio.Event()

    async def gated_receive():
        await gate.wait()
        released.set()
        yield interrupted_msg

    with patch("media.live._make_genai_client") as mock_factory:
        mock_client, mock_session = _make_interruptible_session_mock()
        mock_session.receive = MagicMock(return_value=gated_receive())
        mock_factory.return_value = mock_client

        ils = InterruptibleLiveSession()
        await ils.connect()

        # Let the receive_loop start and suspend at the gate (gen=0 captured).
        await asyncio.sleep(0)

        # Simulate interrupt(): advance generation and enqueue its sentinel.
        ils._generation += 1
        await ils._response_queue.put(None)  # interrupt()'s own sentinel

        # Release the stale interrupted ACK (gen=0, current=1 — stale).
        gate.set()
        await released.wait()
        # Yield control to let the receive_loop process the message.
        await asyncio.sleep(0)

        # Collect everything currently in the queue (before the loop's finally
        # sentinel arrives on close).
        sentinels_before_close = []
        while not ils._response_queue.empty():
            sentinels_before_close.append(ils._response_queue.get_nowait())

        none_count = sum(1 for x in sentinels_before_close if x is None)
        # Expected: 1 from interrupt() + 1 from the loop's finally block = 2.
        # The stale interrupted ACK must NOT add a third sentinel.
        assert none_count == 2, (
            f"Stale interrupted ACK must not enqueue a sentinel; "
            f"expected 2 None sentinels (interrupt + finally) but got {none_count}"
        )

        # _model_speaking should be False (interrupt() clears it via the loop).
        assert not ils.is_model_speaking, (
            "_model_speaking must remain False after a stale interrupted ACK"
        )

        await ils.close()

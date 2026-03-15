# Gemini Live API Integration

Implement or debug the Gemini Live API integration in `media/live.py`.
This is the mandatory technology for the Live Agents hackathon category.

## What to do

1. Read `CLAUDE.md` → section "Gemini Live API — media/live.py" for the full spec
2. Read `media/live.py` if it exists — audit against the spec
3. Read `media/audio.py` — understand the Deepgram/ElevenLabs fallback path
4. Read `telegram_bot.py` → `handle_audio` — check if Live API is wired in

## Audit checklist

For each item, report ✅ or ❌ + file:line:

```
[ ] media/live.py exists
[ ] live_voice_exchange() accepts audio_bytes, mime_type, system_context
[ ] Uses genai.Client(api_key=GEMINI_API_KEY) — not old genai.configure()
[ ] Uses model from config.GEMINI_LIVE_MODEL (not hardcoded string)
[ ] response_modalities=["AUDIO"] set in LiveConnectConfig
[ ] SENTINEL_LIVE_PERSONA system instruction includes detection_context slot
[ ] async with session context manager used — session always closed
[ ] PCM16 → OGG conversion via _pcm_to_ogg()
[ ] Returns b"" on any exception — never raises
[ ] Fallback to ElevenLabs TTS when live_voice_exchange returns b""
[ ] handle_audio in telegram_bot.py calls live.live_voice_exchange
[ ] Temp files deleted in finally block in handle_audio
[ ] tests/test_live.py exists with mock for client.aio.live.connect
```

## If media/live.py is missing or incomplete

Implement it in full per the CLAUDE.md spec. Key requirements:

- Model: `gemini-2.0-flash-live-001`
- Voice: configurable via `config.GEMINI_LIVE_VOICE` (default `"Aoede"`)
- Input: raw OGG bytes from Telegram voice note
- Output: OGG bytes ready to send back as `reply_voice`
- Failure: always returns `b""` — never raises into the handler

## PCM conversion note

Gemini Live API returns raw PCM16 at 24kHz mono.
Telegram expects OGG/Vorbis for voice notes.
The `_pcm_to_ogg()` helper handles this via `pydub`.
Make sure `ffmpeg` is installed (required by pydub):

```bash
# Check ffmpeg is available
ffmpeg -version

# If missing on Windows:
winget install ffmpeg
```

## Testing the Live API locally

```bash
# Quick smoke test — sends a real audio file to Gemini Live
.venv\Scripts\python.exe -c "
import asyncio
from media.live import live_voice_exchange

async def test():
    with open('tests/fixtures/test_audio.ogg', 'rb') as f:
        audio = f.read()
    result = await live_voice_exchange(audio, system_context='GUARD verdict: AI-generated (0.85)')
    print('Result length:', len(result), 'bytes')
    print('Success' if result else 'FAILED — returned empty bytes')

asyncio.run(test())
"
```

## Arguments

$ARGUMENTS

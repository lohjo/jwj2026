# Add Detection Module

Scaffold and implement a new detection module for SENTINEL. Follow every step
in order. Do not skip the test step.

## Arguments

Pass the module name and type:
  `/add-detection-module <name> <type>`

Where:
- `<name>` = e.g. `audio_deepfake`, `url_phishing`, `screenshot_manipulation`
- `<type>` = `pipeline` (text-based) or `media` (file/binary-based)

$ARGUMENTS

## Step 1 — Plan

Before writing any code, answer:
1. What does this module detect?
2. What API or model does it call?
3. What is its input type (text | file_path | bytes)?
4. What is its output dict shape?
5. Which handler(s) in telegram_bot.py should call it?
6. Should it run concurrently with existing detections via asyncio.gather?

Output the plan as a short bullet list. Wait for implicit approval before Step 2.

## Step 2 — Create the module file

**For pipeline/ modules (text-based):**
File: `pipeline/{name}.py`

```python
"""
{name}.py — {description}
Part of SENTINEL detection pipeline.
"""
import logging
import asyncio
from config import GEMINI_API_KEY  # or whichever keys needed
from pipeline.insights import call_llm  # all LLM calls go here


async def detect_{name}(content: str, context: str = "") -> dict:
    """
    Detect {what} in text content.

    Args:
        content: English text to analyse (always English — translation handled upstream).
        context: Optional context string (e.g. "forwarded message", "image caption").

    Returns:
        dict with keys: detected (bool), type (str), explanation (str), confidence (float)
        Always returns a dict — never raises.
    """
    FALLBACK = {
        "detected": False,
        "type": "unknown",
        "explanation": "{Name} check unavailable.",
        "confidence": 0.0,
    }

    try:
        prompt = f"""
You are analysing content for {what}.

Content:
{content[:2000]}

Respond in JSON only — no markdown, no preamble:
{{
  "detected": true or false,
  "type": "none | type_a | type_b | unknown",
  "explanation": "one paragraph plain-language explanation",
  "confidence": 0.0 to 1.0
}}
"""
        import json, re
        raw = await call_llm(prompt)
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(clean)

    except Exception as e:
        logging.warning(f"[{name}] Detection failed: {e}")
        return FALLBACK
```

**For media/ modules (file-based):**
File: `media/{name}.py`

Same pattern but accepts `file_path: str` instead of `content: str`.
Uses `genai.Client(api_key=GEMINI_API_KEY).models.generate_content()` for vision tasks.

## Step 3 — Wire into detector.py

Open `pipeline/detector.py`. Add the new module to `run_full_detection()`:

```python
# Add to asyncio.gather call alongside existing detections
results = await asyncio.gather(
    guard.run_guard_detection(english_text),
    detect_misinformation(english_text),
    new_module.detect_{name}(english_text),  # ← add here
    return_exceptions=True,
)
```

Add the result to the returned dict.

## Step 4 — Wire into telegram_bot.py handler

In the appropriate handler (`handle_text`, `handle_photo`, etc.):
- Import the new module
- Add it to the `asyncio.gather` call
- Pass the result to `run_insights()` as a new optional parameter if needed

## Step 5 — Write tests

Create `tests/test_{name}.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from pipeline.{name} import detect_{name}  # or media.{name}


@pytest.mark.asyncio
async def test_detect_{name}_returns_correct_dict_on_success():
    with patch("pipeline.{name}.call_llm") as mock_llm:
        mock_llm.return_value = '{{"detected": true, "type": "type_a", "explanation": "test", "confidence": 0.9}}'
        result = await detect_{name}("test content")
        assert result["detected"] is True
        assert "explanation" in result
        assert "confidence" in result


@pytest.mark.asyncio
async def test_detect_{name}_returns_fallback_on_failure():
    with patch("pipeline.{name}.call_llm") as mock_llm:
        mock_llm.side_effect = Exception("API down")
        result = await detect_{name}("test content")
        assert result["detected"] is False
        assert result["confidence"] == 0.0
        # Must never raise


@pytest.mark.asyncio
async def test_detect_{name}_never_raises():
    with patch("pipeline.{name}.call_llm") as mock_llm:
        mock_llm.side_effect = Exception("complete failure")
        try:
            result = await detect_{name}("test content")
        except Exception as e:
            pytest.fail(f"detect_{name} raised unexpectedly: {e}")
```

## Step 6 — Run tests

```bash
.venv\Scripts\python.exe -m pytest tests/test_{name}.py -v
.venv\Scripts\python.exe -m pytest tests/ -v  # full suite — must stay green
```

## Step 7 — Update ARCHITECTURE.md

Add the new module to the module dependency graph and the key files table.

## Constraints

- All LLM calls go through `pipeline/insights.py::call_llm()` — no inline Gemini
- Module must never raise — always return the FALLBACK dict
- No `os.getenv()` in the module — import constants from `config.py`
- Temp files (if any) deleted in `finally` blocks
- `asyncio.to_thread()` for any blocking calls

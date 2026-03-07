import requests
import asyncio
import httpx
import re
import json
from dotenv import load_dotenv
import os
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin
from langdetect import detect, LangDetectException
from google.genai.types import Content, Part

load_dotenv()
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8080")

# ── §1: Model Type Detection Helpers ─────────────────────────────────────────

def is_reasoning_model(model_name: str) -> bool:
    """Check if the model is a reasoning model (e.g. Llama-SEA-LION-v3.5-70B-R)."""
    return model_name.endswith('-R')

def is_gemma_model(model_name: str) -> bool:
    """Check if the model is a Gemma-based model (text-based tool calling)."""
    return "Gemma" in model_name

# ── §3: Tool Schema Builder ──────────────────────────────────────────────────

def build_tool_schema() -> List[Dict[str, Any]]:
    """
    Build OpenAI-compatible tool schema for native function-calling models.
    Always includes additionalProperties: False per memory.md §3.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "run_guard_detection",
                "description": "Run SEA-LION GUARD to detect if content is AI-generated.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The text content to analyse. Should be in English."
                        },
                        "content_type": {
                            "type": "string",
                            "description": "One of 'text', 'image_caption', 'audio_transcript', 'video_transcript'.",
                            "enum": ["text", "image_caption", "audio_transcript", "video_transcript"]
                        },
                        "source_lang": {
                            "type": "string",
                            "description": "ISO 639-1 language code of the original source language."
                        }
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_insights",
                "description": "Generate a plain-language explanation of the detection result.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The original user-submitted content."
                        },
                        "detection_result": {
                            "type": "object",
                            "description": "Output from run_guard_detection."
                        }
                    },
                    "required": ["content", "detection_result"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "searxng_search",
                "description": "Search the web using SearXNG for contextual grounding.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query string."
                        },
                        "language": {
                            "type": "string",
                            "description": "Language code (default: 'en')."
                        }
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
    ]


# ── §4: Text-Based Tool Call Parser (Gemma / Reasoning) ──────────────────────

def parse_tool_calls_from_text(content: str) -> Optional[List[Dict[str, Any]]]:
    """
    Parse tool calls from text content for Gemma/Reasoning models
    that don't return structured tool_calls.
    
    Args:
        content: The assistant message content to parse.
    
    Returns:
        List of tool call dicts, or None if no tool calls found.
    """
    if not content or not isinstance(content, str):
        return None

    # Extract from ```tool_code blocks
    tool_code_pattern = r'```tool_code\s*([\s\S]*?)\s*```'
    matches = re.findall(tool_code_pattern, content)
    search_content = '\n'.join(matches) if matches else content

    patterns = [
        (r'run_guard_detection\s*\(\s*content\s*=\s*[\'"]([^\'"]+)[\'"]\s*\)', "run_guard_detection", "content"),
        (r'run_insights\s*\(\s*content\s*=\s*[\'"]([^\'"]+)[\'"]\s*\)', "run_insights", "content"),
        (r'searxng_search\s*\(\s*query\s*=\s*[\'"]([^\'"]+)[\'"]\s*\)', "searxng_search", "query"),
    ]

    results = []
    for pattern, func_name, param_name in patterns:
        for i, match in enumerate(re.findall(pattern, search_content)):
            results.append({
                "id": f"text_parsed_{func_name}_{i}",
                "function": {
                    "name": func_name,
                    "arguments": json.dumps({param_name: match})
                }
            })
    return results if results else None


def extract_tool_calls(data: dict) -> Optional[List]:
    """
    Extract native tool_calls from an OpenAI-style API response (§4).
    For Llama models that return structured tool_calls.
    """
    choice = data.get("choices", [{}])[0]
    return choice.get("message", {}).get("tool_calls")


# ── §10: Input Sanitization ──────────────────────────────────────────────────

def sanitize_input(text: str, max_length: int = 10000) -> str:
    """
    Sanitize user input before passing to tool arguments (§10).
    
    Args:
        text: Raw user input text.
        max_length: Maximum allowed length (default: 10000 chars).
    
    Returns:
        Sanitized text string.
    
    Raises:
        ValueError: If text is empty or not a string.
    """
    if not text or not isinstance(text, str):
        raise ValueError("Input text must be a non-empty string")
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    # Truncate to max length
    if len(text) > max_length:
        text = text[:max_length]
    
    return text


# ── Persistent async HTTP client (§11) ───────────────────────────────────────

_http_client: httpx.AsyncClient | None = None

def get_http_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient with sensible timeouts and limits (§11)."""
    global _http_client
    if _http_client is None or getattr(_http_client, "is_closed", False):
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


# ── §8/§11: Async SearXNG Search (replaces sync version) ─────────────────────

async def searxng_search_async(
    query: str,
    categories: Optional[List[str]] = None,
    engines: Optional[List[str]] = None,
    language: Optional[str] = None,
    pageno: int = 1,
    time_range: Optional[str] = None,
    format: str = "json",
    safesearch: int = 1,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Async version of searxng_search using shared httpx connection pool (§11).
    
    Args:
        query: The search query string.
        categories: List of search categories.
        engines: List of specific engines to use.
        language: Language code (e.g., "en").
        pageno: Page number for pagination (default: 1).
        time_range: Time range filter ("day", "month", "year").
        format: Output format ("json", "csv", "rss").
        safesearch: Safe search level (0=off, 1=moderate, 2=strict).
        timeout: Request timeout in seconds (§9: explicit timeout).
    
    Returns:
        Dictionary containing search results.
    """
    # §9: Validate inputs
    if not query or not isinstance(query, str):
        raise ValueError("Search query must be a non-empty string")
    
    query = sanitize_input(query, max_length=500)
    
    search_url = urljoin(SEARXNG_URL, '/search')
    params = {
        'q': query,
        'pageno': pageno,
        'format': format,
        'safesearch': safesearch
    }
    if categories:
        params['categories'] = ','.join(categories)
    if engines:
        params['engines'] = ','.join(engines)
    if language:
        params['language'] = language
    if time_range:
        params['time_range'] = time_range

    client = get_http_client()
    try:
        resp = await asyncio.wait_for(
            client.get(search_url, params=params),
            timeout=timeout,
        )
        resp.raise_for_status()
        if format == 'json':
            return resp.json()
        else:
            return {'raw_response': resp.text, 'status_code': resp.status_code}
    except asyncio.TimeoutError:
        return {"error": "Search timeout", "results": []}
    except Exception as e:
        return {"error": str(e), "results": []}


# Keep sync version for backward compatibility but mark deprecated
def searxng_search(
    query: str,
    categories: Optional[List[str]] = None,
    engines: Optional[List[str]] = None,
    language: Optional[str] = None,
    pageno: int = 1,
    time_range: Optional[str] = None,
    format: str = "json",
    safesearch: int = 1,
    timeout: int = 10
) -> Dict[str, Any]:
    """
    Sync SearXNG search. Prefer searxng_search_async for new code (§11).
    """
    # §9: Validate inputs
    if not query or not isinstance(query, str):
        raise ValueError("Search query must be a non-empty string")
    
    query = sanitize_input(query, max_length=500)
    
    search_url = urljoin(SEARXNG_URL, '/search')
    params = {
        'q': query, 'pageno': pageno, 'format': format, 'safesearch': safesearch
    }
    if categories:
        params['categories'] = ','.join(categories)
    if engines:
        params['engines'] = ','.join(engines)
    if language:
        params['language'] = language
    if time_range:
        params['time_range'] = time_range

    try:
        response = requests.get(search_url, params=params, timeout=timeout)
        response.raise_for_status()
        if format == 'json':
            return response.json()
        else:
            return {'raw_response': response.text, 'status_code': response.status_code}
    except requests.RequestException as e:
        raise requests.RequestException(f"SearXNG search failed: {str(e)}")
    except ValueError as e:
        if format == 'json':
            raise ValueError(f"Invalid JSON response from SearXNG: {str(e)}")
        raise


# ── Language Detection ────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """
    Detect the language of the given text using langdetect.
    
    Args:
        text: The text to detect the language of.
    
    Returns:
        ISO 639-1 language code (e.g., "en", "zh-cn", "ms", "ta").
        On failure, returns "en" as a safe default.
    """
    # §9: Validate input
    if not text or not isinstance(text, str):
        return "en"
    
    try:
        detected_lang = detect(text)
        return detected_lang
    except LangDetectException:
        print(f"[WARN] Language detection failed for text, defaulting to English")
        return "en"
    except Exception:
        return "en"


# ── Translation Bridge ────────────────────────────────────────────────────────

async def translate_to_english(
    text: str, source_lang: str, runner, user_id: str, session_id: str
) -> str:
    """
    Translate text from source language to English using the translator subagent.
    
    Args:
        text: The text to translate.
        source_lang: ISO 639-1 language code of the source language.
        runner: Google ADK Runner instance.
        user_id: User ID for the session.
        session_id: Session ID for the runner.
    
    Returns:
        Translated English text, or original text on failure (fail-safe §9).
    """
    if source_lang == "en":
        return text
    
    # §9: Validate inputs
    if not text or not isinstance(text, str):
        return text
    
    try:
        message = Content(
            role='user',
            parts=[Part(text=f"Translate the following {source_lang} text to English:\n{text}")]
        )
        translated_text = ""
        async for event in runner.run_async(user_id, session_id, message):
            if hasattr(event, 'text') and event.text:
                translated_text += event.text
            if hasattr(event, 'is_final_response') and event.is_final_response():
                break
        return translated_text.strip() if translated_text else text
    except Exception as e:
        print(f"[WARN] translate_to_english failed: {e}, returning original text")
        return text


async def translate_from_english(
    text: str, target_lang: str, runner, user_id: str, session_id: str
) -> str:
    """
    Translate text from English to target language using the translator subagent.
    
    Args:
        text: The English text to translate.
        target_lang: ISO 639-1 language code of the target language.
        runner: Google ADK Runner instance.
        user_id: User ID for the session.
        session_id: Session ID for the runner.
    
    Returns:
        Translated text, or original text on failure (fail-safe §9).
    """
    if target_lang == "en":
        return text
    
    if not text or not isinstance(text, str):
        return text
    
    try:
        message = Content(
            role='user',
            parts=[Part(text=f"Translate the following English text to {target_lang}:\n{text}")]
        )
        translated_text = ""
        async for event in runner.run_async(user_id, session_id, message):
            if hasattr(event, 'text') and event.text:
                translated_text += event.text
            if hasattr(event, 'is_final_response') and event.is_final_response():
                break
        return translated_text.strip() if translated_text else text
    except Exception as e:
        print(f"[WARN] translate_from_english failed: {e}, returning original text")
        return text


# ── SEA-LION GUARD Detection (§8: input validation + timeout) ─────────────────

async def run_guard_detection(
    content: str, content_type: str = "text", source_lang: str = "en", timeout: float = 25.0
) -> Dict[str, Any]:
    """
    Run SEA-LION GUARD to detect if content is AI-generated.
    
    Args:
        content: The text content to analyse. Should be in English.
        content_type: One of 'text', 'image_caption', 'audio_transcript', 'video_transcript'.
        source_lang: ISO 639-1 code. Warning logged if not 'en'.
        timeout: Request timeout in seconds (§9).
    
    Returns:
        Dict with: is_ai_generated, confidence, label, raw_response.
    """
    # §8/§9: Validate inputs
    if not content or not isinstance(content, str):
        raise ValueError("Content must be a non-empty string")
    
    content = sanitize_input(content)
    
    valid_types = {'text', 'image_caption', 'audio_transcript', 'video_transcript'}
    if content_type not in valid_types:
        raise ValueError(f"content_type must be one of {valid_types}")
    
    if source_lang != "en":
        print(f"[WARN] run_guard_detection received non-English input: {source_lang}")

    api_base = os.getenv("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    guard_model = os.getenv("GUARD_MODEL", "aisingapore/SEA-LION-GUARD")

    # §2: Model-specific request configuration
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": guard_model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    
    # §2: Only add tools param for non-Gemma, non-Reasoning models
    if not is_gemma_model(guard_model) and not is_reasoning_model(guard_model):
        # GUARD is a detection model, not a tool-calling model — no tools needed
        pass

    client = get_http_client()
    try:
        resp = await asyncio.wait_for(
            client.post(f"{api_base}/chat/completions", json=payload, headers=headers),
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["choices"][0]["message"]["content"]
        is_ai = "ai-generated" in raw_text.lower()
        return {
            "is_ai_generated": is_ai,
            "confidence": None,
            "label": raw_text.strip(),
            "raw_response": data,
        }
    except asyncio.TimeoutError:
        return {"error": "API timeout", "is_ai_generated": None, "confidence": None, "label": "timeout"}
    except Exception as e:
        return {"error": str(e), "is_ai_generated": None, "confidence": None, "label": "detection_failed"}


# ── SEA-LION Insights (§8: input validation + timeout) ────────────────────────

async def run_insights(
    content: str, detection_result: Dict[str, Any], timeout: float = 25.0
) -> Dict[str, Any]:
    """
    Use SEA-LION v4 to generate a plain-language explanation of the detection result.
    
    Args:
        content: The original user-submitted content.
        detection_result: Output from run_guard_detection.
        timeout: Request timeout in seconds (§9).
    
    Returns:
        Dict with: explanation, suggested_action.
    """
    # §8/§9: Validate inputs
    if not content or not isinstance(content, str):
        raise ValueError("Content must be a non-empty string")
    if not isinstance(detection_result, dict):
        raise ValueError("detection_result must be a dictionary")
    
    content = sanitize_input(content)
    
    api_base = os.getenv("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL", "aisingapore/Llama-SEA-LION-v3-70B-IT")

    prompt = f"""
You are analysing the following content for AI-generation signals.

Content: {content}
Detection verdict: {detection_result.get('label', 'Unknown')}

Provide:
1. A clear explanation of why this content may or may not be AI-generated.
2. Specific linguistic/visual/structural signals observed.
3. A recommended action for the user (e.g. verify source, treat as AI-generated, inconclusive).

Be concise. Do not over-censor. If evidence is weak, say so.
"""

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0,
    }

    client = get_http_client()
    try:
        resp = await asyncio.wait_for(
            client.post(f"{api_base}/chat/completions", json=payload, headers=headers),
            timeout=timeout,
        )
        resp.raise_for_status()
        explanation = resp.json()["choices"][0]["message"]["content"]
        return {"explanation": explanation, "suggested_action": "See explanation above."}
    except asyncio.TimeoutError:
        return {"error": "API timeout", "explanation": "Insights unavailable.", "suggested_action": "Manual review recommended."}
    except Exception as e:
        return {"error": str(e), "explanation": "Insights unavailable.", "suggested_action": "Manual review recommended."}


# ── Image Analysis (Gemini) ───────────────────────────────────────────────────

async def analyse_image_with_gemini(image_path: str) -> Dict[str, Any]:
    """
    Use Gemini 2.5 Flash to analyse an image for AI-generation signals.

    Pipeline:
    1. Load image from disk
    2. Send to Gemini with a structured prompt asking for:
       - Image description / caption
       - OCR text extraction (if any text is visible)
       - AI-generation signal analysis (artifacts, symmetry, texture anomalies)
    3. Return structured dict

    Args:
        image_path: Path to the image file on disk.

    Returns:
        Dictionary with keys:
        - caption (str): Description of the image content
        - ocr_text (str | None): Any text extracted from the image
        - ai_signals (str): Analysis of potential AI-generation indicators
        - raw_response (str): Full Gemini response text
    """
    import google.genai as genai
    from PIL import Image

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return {"error": "GEMINI_API_KEY not set", "caption": "", "ocr_text": None, "ai_signals": ""}

    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel(os.getenv("MODEL_NAME", "gemini-2.5-flash"))

        img = Image.open(image_path)

        prompt = """Analyse this image in detail:

1. **Description**: Describe what is shown in the image (1-2 sentences).
2. **Text extraction**: If there is any visible text in the image, extract it exactly as written.
   If no text, write "No text detected".
3. **AI-generation signals**: Look for signs that this image may be AI-generated:
   - Unnatural textures, lighting, or shadows
   - Warped or inconsistent geometry (extra fingers, asymmetric features)
   - Repeating patterns, tiling artifacts
   - Overly smooth skin or surfaces
   - Inconsistent reflections or perspective
   - Watermarks from known AI generators
   If no AI signals are found, say so.

Respond in this exact format:
DESCRIPTION: <your description>
OCR_TEXT: <extracted text or "No text detected">
AI_SIGNALS: <your analysis>"""

        response = model.generate_content([prompt, img])
        text = response.text if hasattr(response, 'text') else str(response)

        # Parse structured response
        caption = ""
        ocr_text = None
        ai_signals = ""

        for line in text.split('\n'):
            if line.startswith("DESCRIPTION:"):
                caption = line.replace("DESCRIPTION:", "").strip()
            elif line.startswith("OCR_TEXT:"):
                raw = line.replace("OCR_TEXT:", "").strip()
                ocr_text = None if raw.lower() == "no text detected" else raw
            elif line.startswith("AI_SIGNALS:"):
                ai_signals = line.replace("AI_SIGNALS:", "").strip()

        return {
            "caption": caption or text[:200],
            "ocr_text": ocr_text,
            "ai_signals": ai_signals,
            "raw_response": text,
        }
    except Exception as e:
        return {"error": str(e), "caption": "", "ocr_text": None, "ai_signals": ""}


# ── Audio Transcription (Deepgram) ────────────────────────────────────────────

async def transcribe_audio_deepgram(audio_path: str) -> Dict[str, Any]:
    """
    Transcribe audio using Deepgram's Nova-2 model.

    Args:
        audio_path: Path to the audio file (OGG, MP3, WAV, M4A supported).

    Returns:
        Dictionary with keys:
        - transcript (str): The transcribed text
        - confidence (float): Overall transcription confidence (0.0-1.0)
        - language (str): Detected language code
        - duration (float): Audio duration in seconds
        - error (str | None): Error message if transcription failed
    """
    try:
        from deepgram import DeepgramClient, PrerecordedOptions, FileSource

        api_key = os.getenv("DEEPGRAM_API_KEY", "")
        if not api_key:
            return {"error": "DEEPGRAM_API_KEY not set", "transcript": "", "confidence": 0.0}

        client = DeepgramClient(api_key)

        with open(audio_path, "rb") as f:
            buffer_data = f.read()

        payload: FileSource = {"buffer": buffer_data}
        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
            language="en",        # Auto-detects but defaults to English
            detect_language=True,
            punctuate=True,
        )

        response = await asyncio.to_thread(
            client.listen.rest.v1.transcribe_file, payload, options
        )

        result = response.results
        transcript = result.channels[0].alternatives[0].transcript
        confidence = result.channels[0].alternatives[0].confidence
        detected_lang = result.channels[0].detected_language or "en"
        duration = response.metadata.duration if hasattr(response, 'metadata') else 0.0

        return {
            "transcript": transcript,
            "confidence": confidence,
            "language": detected_lang,
            "duration": duration,
            "error": None,
        }
    except Exception as e:
        return {"error": str(e), "transcript": "", "confidence": 0.0, "language": "en", "duration": 0.0}


# ── Text-to-Speech (ElevenLabs) ───────────────────────────────────────────────

async def synthesise_speech_elevenlabs(text: str, output_path: str) -> Dict[str, Any]:
    """
    Convert text to speech using ElevenLabs API.

    Args:
        text: The text to convert to speech (max 5000 chars).
        output_path: Path to save the generated audio file (MP3).

    Returns:
        Dictionary with keys:
        - success (bool): Whether the audio was generated
        - output_path (str): Path to the generated file
        - error (str | None): Error message if failed
    """
    try:
        from elevenlabs import ElevenLabs

        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Default: Rachel
        if not api_key:
            return {"success": False, "output_path": "", "error": "ELEVENLABS_API_KEY not set"}

        # Truncate to API limit
        text = text[:5000]

        client = ElevenLabs(api_key=api_key)
        audio = await asyncio.to_thread(
            client.text_to_speech.convert,
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
        )

        with open(output_path, "wb") as f:
            for chunk in audio:
                f.write(chunk)

        return {"success": True, "output_path": output_path, "error": None}
    except Exception as e:
        return {"success": False, "output_path": "", "error": str(e)}


# ── Video Analysis ────────────────────────────────────────────────────────────

async def analyse_video(video_path: str) -> Dict[str, Any]:
    """
    Analyse a video for AI-generation signals by:
    1. Extracting frames at 1fps (max 5 frames)
    2. Sending key frames to Gemini for visual analysis
    3. Extracting audio track and transcribing via Deepgram
    4. Combining visual + audio analysis

    Args:
        video_path: Path to the video file on disk.

    Returns:
        Dictionary with keys:
        - frame_descriptions (list[str]): Gemini descriptions of sampled frames
        - audio_transcript (str): Deepgram transcript of audio track
        - ai_signals (str): Combined AI-generation signal analysis
        - frames_checked (int): Number of frames analysed
        - error (str | None): Error message if analysis failed
    """
    import tempfile

    try:
        # Step 1: Extract frames
        from config import extract_frames
        frames = await asyncio.to_thread(extract_frames, video_path)
        frames = frames[:5]  # Limit to 5 frames

        # Step 2: Analyse frames with Gemini
        frame_descriptions = []
        combined_ai_signals = []
        for frame_path in frames:
            result = await analyse_image_with_gemini(frame_path)
            frame_descriptions.append(result.get("caption", ""))
            if result.get("ai_signals"):
                combined_ai_signals.append(result["ai_signals"])

        # Step 3: Extract and transcribe audio
        audio_transcript = ""
        try:
            audio_path = tempfile.mktemp(suffix=".wav")
            # Extract audio track using ffmpeg (or pydub)
            from pydub import AudioSegment
            audio = await asyncio.to_thread(AudioSegment.from_file, video_path)
            await asyncio.to_thread(audio.export, audio_path, format="wav")
            transcript_result = await transcribe_audio_deepgram(audio_path)
            audio_transcript = transcript_result.get("transcript", "")
            # Clean up
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception:
            audio_transcript = "(Audio extraction failed)"

        # Step 4: Clean up frame files
        for frame_path in frames:
            if os.path.exists(frame_path):
                os.remove(frame_path)

        return {
            "frame_descriptions": frame_descriptions,
            "audio_transcript": audio_transcript,
            "ai_signals": " | ".join(combined_ai_signals) if combined_ai_signals else "No strong AI signals detected in frames",
            "frames_checked": len(frames),
            "error": None,
        }
    except Exception as e:
        return {
            "frame_descriptions": [],
            "audio_transcript": "",
            "ai_signals": "",
            "frames_checked": 0,
            "error": str(e),
        }

# ── ClickHouse Logger ─────────────────────────────────────────────────────────

def log_to_clickhouse(
    user_id: str,
    content_type: str,
    content_preview: str,
    detection_label: str,
    confidence: Optional[float],
    explanation: str,
) -> Dict[str, Any]:
    """
    Log a detection event to ClickHouse for real-time analytics.
    """
    # §9: Validate inputs
    if not user_id or not isinstance(user_id, str):
        return {"status": "failed", "error": "Invalid user_id"}
    if not content_type or content_type not in ('text', 'image', 'audio', 'video'):
        return {"status": "failed", "error": "Invalid content_type"}
    
    try:
        from clickhouse_driver import Client
        client = Client(
            host=os.getenv("CLICKHOUSE_HOST"),
            port=int(os.getenv("CLICKHOUSE_PORT", 9000)),
            user=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DB", "agent_logs"),
        )
        client.execute(
            "INSERT INTO detection_events (user_id, content_type, content_preview, detection_label, confidence, explanation) VALUES",
            [(user_id, content_type, (content_preview or "")[:200], detection_label or "", confidence, explanation or "")],
        )
        return {"status": "logged"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


# ── Message Format (§14) ─────────────────────────────────────────────────────

def format_detection_response(
    content_type: str,
    verdict: str,
    is_ai_generated: bool | None,
    confidence: float | None,
    explanation: str,
    caption: str = "",
    ocr_text: str | None = None,
    transcript: str = "",
    ai_signals: str = "",
    frames_checked: int = 0,
) -> str:
    """
    Format a detection result into a user-friendly Telegram message.

    Args:
        content_type: One of 'text', 'image', 'audio', 'video'.
        verdict: Raw verdict label from GUARD.
        is_ai_generated: Boolean detection result (True/False/None).
        confidence: Confidence score 0.0-1.0, or None.
        explanation: Plain-language explanation from insights model.
        caption: Image caption (for image content type).
        ocr_text: Extracted text from image OCR (for image content type).
        transcript: Audio/video transcript text.
        ai_signals: Detected AI-generation signals.
        frames_checked: Number of video frames analysed.

    Returns:
        Formatted Markdown string for Telegram.
    """
    # Verdict emoji
    if is_ai_generated is True:
        verdict_emoji = "🔴"
        verdict_label = "Likely AI-Generated"
    elif is_ai_generated is False:
        verdict_emoji = "🟢"
        verdict_label = "Likely Human-Generated"
    else:
        verdict_emoji = "🟡"
        verdict_label = "Inconclusive"

    # Content type header
    type_icons = {"text": "📝", "image": "🖼️", "audio": "🎤", "video": "🎬"}
    type_icon = type_icons.get(content_type, "📄")

    # Confidence bar
    if confidence is not None:
        pct = int(confidence * 100)
        filled = int(confidence * 10)
        bar = "█" * filled + "░" * (10 - filled)
        confidence_line = f"*Confidence*: {bar} {pct}%"
    else:
        confidence_line = "*Confidence*: Not available"

    # Build message
    lines = []
    lines.append(f"{type_icon} *{content_type.upper()} ANALYSIS*")
    lines.append("")
    lines.append(f"{verdict_emoji} *Verdict*: {verdict_label}")
    lines.append(confidence_line)
    lines.append("")

    # Content preview section (varies by type)
    if content_type == "image":
        if caption:
            lines.append(f"🔎 *Image Content*: {caption[:150]}")
        if ocr_text:
            lines.append(f"📖 *Detected Text*: _{ocr_text[:150]}_")
        if ai_signals:
            lines.append(f"⚠️ *Visual Signals*: {ai_signals[:200]}")
        lines.append("")
    elif content_type == "audio":
        if transcript:
            lines.append(f"📝 *Transcript*: _{transcript[:200]}_")
        lines.append("")
    elif content_type == "video":
        if frames_checked:
            lines.append(f"🎞️ *Frames Analysed*: {frames_checked}")
        if transcript:
            lines.append(f"📝 *Audio Transcript*: _{transcript[:150]}_")
        if ai_signals:
            lines.append(f"⚠️ *Visual Signals*: {ai_signals[:200]}")
        lines.append("")

    # Explanation
    lines.append("💡 *Analysis*")
    clean_explanation = explanation.strip()
    if len(clean_explanation) > 500:
        clean_explanation = clean_explanation[:497] + "..."
    lines.append(clean_explanation)
    lines.append("")

    # Footer
    lines.append("─" * 20)
    lines.append("🤖 _Powered by SEA-LION GUARD + Gemini_")
    lines.append("_This is an automated analysis. Use your own judgement._")

    return "\n".join(lines)
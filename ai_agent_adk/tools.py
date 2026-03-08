import requests
import asyncio
import httpx
import re
import json
import html
import logging
from dotenv import load_dotenv
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin
from langdetect import detect, LangDetectException
from google.genai.types import Content, Part

# Load .env with override=True so project keys take precedence over system env vars
_env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=_env_path, override=True)
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
        logging.warning(f"translate_to_english failed: {e}, returning original text")
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
        logging.warning(f"translate_from_english failed: {e}, returning original text")
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
    guard_model = os.getenv("GUARD_MODEL", "aisingapore/SEA-Guard")

    if not api_key:
        logging.error("[GUARD] OPENAI_API_KEY not set")
        return {"is_ai_generated": None, "confidence": None,
                "label": "api_key_missing", "raw_response": {}}

    # §2: Model-specific request configuration
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": guard_model,
        "messages": [{"role": "user", "content": content[:2000]}],
        "max_tokens": 256,
    }
    
    # §2: Only add tools param for non-Gemma, non-Reasoning models
    if not is_gemma_model(guard_model) and not is_reasoning_model(guard_model):
        # GUARD is a detection model, not a tool-calling model — no tools needed
        pass

    # SEA-Guard returns safety labels (safe/unsafe), not AI-detection verdicts.
    # Run SEA-Guard for safety check, then use Gemini for AI-content detection.
    safety_label = None
    client = get_http_client()
    try:
        resp = await asyncio.wait_for(
            client.post(f"{api_base}/chat/completions", json=payload, headers=headers),
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        raw_text = data["choices"][0]["message"]["content"].strip()
        logging.info(f"[GUARD] SEA-Guard safety response: {raw_text[:200]}")
        safety_label = raw_text.lower()
    except Exception as e:
        logging.warning(f"[GUARD] SEA-Guard safety check failed: {e}")

    # Use Gemini as the primary AI-content detection engine
    # Prefer GEMINI_API_KEY (project-specific) over GOOGLE_API_KEY (system-wide, may be rate-limited)
    gemini_key = os.getenv('GEMINI_API_KEY', '') or os.getenv('GOOGLE_API_KEY', '')
    if gemini_key:
        try:
            import google.genai as genai

            gemini_model = os.getenv('MODEL_NAME', 'gemini-2.5-flash')
            prompt = (
                "Decide whether the following content is AI-generated or human-written. "
                "Reply with exactly three lines:\n"
                "VERDICT: AI or HUMAN\n"
                "PROBABILITY: 0-100\n"
                "LABEL: short label\n\n"
                f"Content:\n{content[:2000]}"
            )

            def _call_gemini():
                try:
                    c = genai.Client(api_key=gemini_key)
                    r = c.models.generate_content(model=gemini_model, contents=prompt)
                    return r.text
                except Exception:
                    logging.exception('[GUARD] Gemini AI-detection failed')
                    return None

            gemini_resp = await asyncio.to_thread(_call_gemini)
            if gemini_resp:
                verdict = None
                prob = None
                label = gemini_resp.strip()
                for line in gemini_resp.splitlines():
                    lu = line.upper().strip()
                    if lu.startswith('VERDICT:'):
                        v = lu.split(':', 1)[1].strip()
                        verdict = 'AI' in v
                    elif lu.startswith('PROBABILITY:'):
                        try:
                            prob = float(re.sub(r'[^0-9.]', '', lu.split(':', 1)[1].strip()))
                            if prob > 1.0:
                                prob = prob / 100.0
                        except Exception:
                            prob = None
                    elif lu.startswith('LABEL:'):
                        label = line.split(':', 1)[1].strip()

                result = {
                    'is_ai_generated': bool(verdict) if verdict is not None else None,
                    'confidence': prob,
                    'label': label,
                    'raw_response': gemini_resp,
                }
                # Attach safety info from SEA-Guard
                if safety_label == 'unsafe':
                    result['safety_flag'] = 'unsafe'
                return result

        except Exception:
            logging.exception('[GUARD] Gemini AI-detection failed')

    # If Gemini is not available, fall back to parsing SEA-Guard response
    if safety_label is not None:
        return {
            "is_ai_generated": None,
            "confidence": None,
            "label": safety_label,
            "safety_flag": safety_label,
            "raw_response": {},
        }

    return {"is_ai_generated": None, "confidence": None,
                "label": "api_error", "raw_response": {}}


# ── AI Misinformation Detection ──────────────────────────────────────────────

async def detect_misinformation(content: str, context_description: str = "") -> dict:
    """
    Detect AI-assisted misinformation in text content using Gemini.

    Focuses on: false factual claims, fabricated quotes, manipulated statistics,
    misleading context, and coordinated inauthentic narratives.

    Args:
        content: English text to analyse (OCR, transcript, or direct input).
        context_description: Optional — e.g. "image caption", "forwarded message".

    Returns:
        dict: misinformation_detected (bool), misinformation_type (str),
              claims (list[str]), explanation (str), confidence (float)
    """
    gemini_key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        logging.warning("[Misinformation] GEMINI_API_KEY / GOOGLE_API_KEY not set")
        return {
            "misinformation_detected": False,
            "misinformation_type": "unknown",
            "claims": [],
            "explanation": "Misinformation check unavailable (no API key).",
            "confidence": 0.0,
        }

    try:
        import google.genai as genai

        os.environ.setdefault("GEMINI_API_KEY", gemini_key)
        os.environ.setdefault("GENAI_API_KEY", gemini_key)

        gemini_model_name = os.getenv("MODEL_NAME", "gemini-2.5-flash")
        source_context = f"Source context: {context_description}\n" if context_description else ""

        prompt = f"""You are a fact-checking assistant specialised in detecting AI-assisted misinformation.

{source_context}Content to analyse:
{content[:2000]}

Analyse for misinformation. Respond in JSON format only — no markdown, no preamble:

{{
  "misinformation_detected": true or false,
  "misinformation_type": "none | fabricated_quote | false_statistic | misleading_context | deepfake_narrative | coordinated_narrative | unknown",
  "claims": ["list of specific suspicious claims, empty array if none"],
  "explanation": "one paragraph plain-language explanation",
  "confidence": 0.0 to 1.0
}}

Rules:
- Only flag where there is clear evidence of manipulation or false claims
- Do NOT flag opinions, clearly marked satire, or uncertain interpretations
- If content is too short or generic to assess, set misinformation_detected to false
- Base assessment only on the content provided, not assumptions"""

        def _call():
            try:
                c = genai.Client(api_key=gemini_key)
                resp = c.models.generate_content(
                    model=gemini_model_name,
                    contents=prompt,
                )
                return resp.text
            except Exception:
                logging.exception("[Misinformation] Gemini call failed")
                return None

        raw = await asyncio.to_thread(_call)
        if raw:
            clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE).strip()
            return json.loads(clean)
    except (json.JSONDecodeError, Exception) as e:
        logging.exception(f"[Misinformation] Detection failed: {e}")

    return {
        "misinformation_detected": False,
        "misinformation_type": "unknown",
        "claims": [],
        "explanation": "Misinformation check unavailable.",
        "confidence": 0.0,
    }


# ── SEA-LION Insights (§8: input validation + timeout) ────────────────────────

async def run_insights(
    content: str, detection_result: Dict[str, Any],
    misinformation_result: Dict[str, Any] = None,
    manipulation_result: Dict[str, Any] = None,
    timeout: float = 25.0
) -> Dict[str, Any]:
    """
    Generate plain-language explanation combining all detection results.

    Args:
        content: The actual English-normalised content (NOT the GUARD label).
        detection_result: Output from run_guard_detection().
        misinformation_result: Output from detect_misinformation() — optional.
        manipulation_result: Output from detect_image_manipulation() — optional.
        timeout: Request timeout in seconds (§9).

    Returns:
        Dict with: explanation (str), suggested_action (str), is_harmful (bool)
    """
    # §8/§9: Validate inputs
    if not content or not isinstance(content, str):
        raise ValueError("Content must be a non-empty string")
    if not isinstance(detection_result, dict):
        raise ValueError("detection_result must be a dictionary")

    content = sanitize_input(content)

    # Build context sections from detection results
    guard_label = detection_result.get("label", "unknown")

    # Skip GUARD context if it errored — don't pollute insights with error strings
    guard_context = ""
    if guard_label not in ("api_error", "timeout", "api_key_missing"):
        guard_verdict = (
            "AI-generated" if detection_result.get("is_ai_generated") is True
            else "Human-generated" if detection_result.get("is_ai_generated") is False
            else "Inconclusive"
        )
        guard_context = f"SEA-LION GUARD verdict: {guard_verdict} ({guard_label[:150]})\n"

    misinfo_context = ""
    if misinformation_result and misinformation_result.get("misinformation_detected"):
        claims = "\n".join(f"- {c}" for c in misinformation_result.get("claims", []))
        misinfo_context = (
            f"Misinformation detected — type: {misinformation_result.get('misinformation_type')}\n"
            f"Suspicious claims:\n{claims or 'See misinformation explanation'}\n"
        )

    manip_context = ""
    if manipulation_result and manipulation_result.get("manipulation_detected"):
        signals = "\n".join(f"- {s}" for s in manipulation_result.get("signals", []))
        manip_context = (
            f"Image manipulation detected — type: {manipulation_result.get('manipulation_type')}\n"
            f"Visual signals:\n{signals or 'See manipulation explanation'}\n"
        )

    insights_prompt = f"""
You are an AI content analyst writing a plain-language report for a general user in Singapore.

Content analysed:
{content[:800]}

Detection results:
{guard_context}{misinfo_context}{manip_context}

Write 2-3 sentences that:
1. State clearly what was found (or not found)
2. Explain the key reasons or signals for the verdict
3. Give one practical recommendation for the user

Rules:
- Plain text only — no bullet points, headers, or markdown
- Be factual and avoid alarmist language
- If evidence is weak or results are inconclusive, say so honestly
- If all checks returned no issues, clearly say the content appears genuine
"""

    HARMFUL_KEYWORDS = [
        "misinformation", "disinformation", "harmful", "dangerous",
        "incite", "violence", "hate", "scam", "fraud", "fake news",
        "manipulated", "fabricated", "deepfake"
    ]

    # Try SEA-LION first
    api_base = os.getenv("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("MODEL", "aisingapore/Llama-SEA-LION-v3-70B-IT")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": insights_prompt}],
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
        is_harmful = any(kw in explanation.lower() for kw in HARMFUL_KEYWORDS)
        return {"explanation": explanation, "suggested_action": "See explanation above.",
                "is_harmful": is_harmful}
    except asyncio.TimeoutError:
        return {"explanation": "Insights unavailable.", "suggested_action": "Manual review recommended.",
                "is_harmful": False}
    except Exception as e:
        # Try Gemini fallback
        err_str = str(e)
        status_code = None
        try:
            if hasattr(e, 'response') and e.response is not None:
                status_code = getattr(e.response, 'status_code', None)
        except Exception:
            status_code = None

        if (status_code == 401) or ('401' in err_str) or ('Unauthorized' in err_str):
            gemini_key = os.getenv('GOOGLE_API_KEY', '') or os.getenv('GEMINI_API_KEY', '')
            if gemini_key:
                try:
                    import google.genai as genai

                    gemini_model = os.getenv('MODEL_NAME', 'gemini-2.5-flash')
                    os.environ.setdefault('GEMINI_API_KEY', gemini_key)
                    os.environ.setdefault('GENAI_API_KEY', gemini_key)

                    def _call_gemini():
                        try:
                            c = genai.Client(api_key=gemini_key)
                            resp = c.models.generate_content(
                                model=gemini_model,
                                contents=insights_prompt,
                            )
                            return resp.text
                        except Exception:
                            logging.exception('[INSIGHTS] Gemini fallback failed')
                            return None

                    gemini_resp = await asyncio.to_thread(_call_gemini)
                    if gemini_resp:
                        is_harmful = any(kw in gemini_resp.lower() for kw in HARMFUL_KEYWORDS)
                        return {"explanation": gemini_resp,
                                "suggested_action": "See explanation above (Gemini fallback).",
                                "is_harmful": is_harmful}
                except Exception:
                    pass

        return {"explanation": "Insights unavailable.", "suggested_action": "Manual review recommended.",
                "is_harmful": False}


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

    gemini_key = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return {"error": "GEMINI_API_KEY / GOOGLE_API_KEY not set", "caption": "", "ocr_text": None, "ai_signals": ""}

    try:
        client = genai.Client(api_key=gemini_key)
        gemini_model = os.getenv("MODEL_NAME", "gemini-2.5-flash")

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

        response = client.models.generate_content(
            model=gemini_model,
            contents=[prompt, img],
        )
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

        # Strip HTML tags and truncate to API limit
        text = re.sub(r'<[^>]+>', '', text)
        text = text[:5000]

        client = ElevenLabs(api_key=api_key)
        audio = await asyncio.to_thread(
            client.text_to_speech.convert,
            text=text,
            voice_id=voice_id,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
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

import hashlib as _hashlib
import sys as _sys
import uuid as _uuid

# Lazy-initialised ClickHouse client (one per process)
_ch_client = None

def _get_ch_client():
    """Return a cached clickhouse-connect client. Never raises."""
    global _ch_client
    if _ch_client is not None:
        return _ch_client
    try:
        import clickhouse_connect
        _ch_client = clickhouse_connect.get_client(
            host=os.getenv("CLICKHOUSE_HOST", "e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud"),
            port=int(os.getenv("CLICKHOUSE_PORT", 8443)),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DB", "agent_logs"),
            secure=True,
        )
        return _ch_client
    except Exception:
        logging.exception("[ClickHouse] Failed to create client")
        return None


def log_to_clickhouse(row_dict: dict) -> Dict[str, Any]:
    """
    Log a detection event to ClickHouse for real-time analytics.

    Accepts a dict matching the detection_events schema. Uses async_insert so
    the caller is never blocked. Safe to call via ``asyncio.to_thread()``.

    Never raises — all exceptions are logged to stderr and swallowed.

    Args:
        row_dict: Dictionary with keys matching the detection_events columns.
            Required: user_id, content_type.
            Optional: session_id, source_language, content_preview, guard_label,
                      guard_verdict, guard_confidence, misinfo_detected, misinfo_type,
                      manipulation_detected, manipulation_type, explanation,
                      is_harmful, processing_ms, model_versions, error_code.

    Returns:
        {"status": "logged"} on success, {"status": "failed", "error": "..."} otherwise.
    """
    try:
        client = _get_ch_client()
        if client is None:
            return {"status": "failed", "error": "ClickHouse client unavailable"}

        # Map guard_verdict string to valid Enum value
        valid_verdicts = {'ai_generated', 'human_generated', 'inconclusive', 'error'}
        raw_verdict = str(row_dict.get("guard_verdict", "error")).lower().replace("-", "_").replace(" ", "_")
        guard_verdict = raw_verdict if raw_verdict in valid_verdicts else "error"

        # Map content_type to valid Enum value
        valid_types = {'text', 'image', 'audio', 'video'}
        ct = str(row_dict.get("content_type", "text")).lower()
        content_type = ct if ct in valid_types else "text"

        # Hash user_id for privacy
        raw_uid = str(row_dict.get("user_id", "unknown"))
        hashed_uid = _hashlib.sha256(raw_uid.encode()).hexdigest()[:16]

        row = [[
            _uuid.uuid4(),                                                 # event_id
            hashed_uid,                                                    # user_id
            str(row_dict.get("session_id", "")),                           # session_id
            content_type,                                                  # content_type
            str(row_dict.get("source_language", "en")),                    # source_language
            str(row_dict.get("content_preview", ""))[:500],                # content_preview
            str(row_dict.get("guard_label", "")),                          # guard_label
            guard_verdict,                                                 # guard_verdict
            row_dict.get("guard_confidence"),                              # guard_confidence (Nullable)
            bool(row_dict.get("misinfo_detected", False)),                 # misinfo_detected
            str(row_dict.get("misinfo_type", "none")),                     # misinfo_type
            bool(row_dict.get("manipulation_detected", False)),            # manipulation_detected
            str(row_dict.get("manipulation_type", "none")),                # manipulation_type
            str(row_dict.get("explanation", "")),                          # explanation
            bool(row_dict.get("is_harmful", False)),                       # is_harmful
            int(row_dict.get("processing_ms", 0)),                         # processing_ms
            row_dict.get("model_versions") or {},                          # model_versions
            str(row_dict.get("error_code", "none")),                       # error_code
        ]]

        columns = [
            "event_id", "user_id", "session_id", "content_type",
            "source_language", "content_preview", "guard_label", "guard_verdict",
            "guard_confidence", "misinfo_detected", "misinfo_type",
            "manipulation_detected", "manipulation_type", "explanation",
            "is_harmful", "processing_ms", "model_versions", "error_code",
        ]

        client.insert(
            "detection_events",
            row,
            column_names=columns,
            settings={"async_insert": 1, "wait_for_async_insert": 0},
        )
        return {"status": "logged"}
    except Exception as exc:
        print(f"[ClickHouse] log_to_clickhouse failed: {exc}", file=_sys.stderr)
        logging.exception("[ClickHouse] log_to_clickhouse failed")
        return {"status": "failed", "error": str(exc)}


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
    # Normalise/interpret confidence (support 0..1 or 0..100 inputs)
    conf_float: float | None = None
    if confidence is not None:
        try:
            c = float(confidence)
            if c > 1.0:
                c = max(0.0, min(100.0, c)) / 100.0
            conf_float = max(0.0, min(1.0, c))
        except Exception:
            conf_float = None

    # Derive a clearer verdict using both boolean flag and raw verdict string
    verdict_normalised = (verdict or "").strip()
    v_low = verdict_normalised.lower()

    def label_for(ai_prob: float | None, ai_flag: bool | None, raw: str) -> tuple[str, str]:
        if ai_flag is True:
            if ai_prob is not None:
                if ai_prob >= 0.9:
                    return ("🔴", "Very Likely AI-Generated")
                if ai_prob >= 0.65:
                    return ("🔴", "Likely AI-Generated")
                if ai_prob >= 0.45:
                    return ("🟠", "Possibly AI-Generated")
                return ("🟡", "Weak AI signals (Inconclusive)")
            return ("🔴", "Likely AI-Generated")

        if ai_flag is False:
            if ai_prob is not None:
                if ai_prob >= 0.9:
                    return ("🟢", "Very Likely Human-Generated")
                if ai_prob >= 0.65:
                    return ("🟢", "Likely Human-Generated")
                if ai_prob >= 0.45:
                    return ("🟡", "Possibly Human-Generated")
                return ("🟡", "Weak human signal (Inconclusive)")
            return ("🟢", "Likely Human-Generated")

        if any(k in raw for k in ("ai", "generated", "bot", "synthetic")):
            if ai_prob is not None and ai_prob >= 0.65:
                return ("🔴", "Likely AI-Generated")
            return ("🟠", "Possible AI-Generated")
        if any(k in raw for k in ("human", "authentic", "real")):
            return ("🟢", "Likely Human-Generated")

        return ("🟡", "Inconclusive")

    verdict_emoji, verdict_label = label_for(conf_float, is_ai_generated, v_low)

    # Content type header
    type_icons = {"text": "📝", "image": "🖼️", "audio": "🎤", "video": "🎬"}
    type_icon = type_icons.get(content_type, "📄")

    # Escape dynamic content for HTML (allow only our tags)
    caption_safe = html.escape(caption or "")
    ocr_safe = html.escape(ocr_text) if ocr_text else None
    transcript_safe = html.escape(transcript or "")
    ai_signals_safe = html.escape(ai_signals or "")
    explanation_safe = html.escape(explanation or "")
    verdict_label_safe = html.escape(verdict_label)
    verdict_normalised_safe = html.escape(verdict_normalised)

    # Confidence bar
    if conf_float is not None:
        pct = int(conf_float * 100)
        filled = int(round(conf_float * 10))
        filled = max(0, min(10, filled))
        bar = "█" * filled + "░" * (10 - filled)
        confidence_line = f"<b>Confidence</b>: <code>{html.escape(bar)} {pct}%</code>"
    else:
        confidence_line = "<b>Confidence</b>: Not available"

    # Build HTML message
    lines = []
    lines.append(f"{type_icon} <b>{html.escape(content_type.upper())} ANALYSIS</b>")

    # Include raw verdict label in parentheses when provided for transparency
    raw_hint = ""
    if verdict_normalised and verdict_normalised.lower() not in verdict_label.lower():
        raw_hint = f" (<code>{verdict_normalised_safe}</code>)"

    lines.append(f"{verdict_emoji} <b>Verdict</b>: {verdict_label_safe}{raw_hint}")
    lines.append(confidence_line)

    # Content preview section
    if content_type == "image":
        if caption_safe:
            lines.append(f"🔎 <b>Image Content</b>: {caption_safe[:150]}")
        if ocr_safe:
            lines.append(f"📖 <b>Detected Text</b>: <i>{ocr_safe[:150]}</i>")
        if ai_signals_safe:
            lines.append(f"⚠️ <b>Visual Signals</b>: {ai_signals_safe[:200]}")
    elif content_type == "audio":
        if transcript_safe:
            lines.append(f"📝 <b>Transcript</b>: <i>{transcript_safe[:200]}</i>")
    elif content_type == "video":
        if frames_checked:
            lines.append(f"🎞️ <b>Frames Analysed</b>: {frames_checked}")
        if transcript_safe:
            lines.append(f"📝 <b>Audio Transcript</b>: <i>{transcript_safe[:150]}</i>")
        if ai_signals_safe:
            lines.append(f"⚠️ <b>Visual Signals</b>: {ai_signals_safe[:200]}")

    # Explanation
    lines.append("")
    lines.append("<b>Analysis</b>")
    clean_explanation = explanation_safe.strip() if explanation_safe else ""
    if len(clean_explanation) > 500:
        clean_explanation = clean_explanation[:497] + "..."
    lines.append(clean_explanation)

    # Footer
    lines.append("──────────────────────")
    lines.append("🤖 <i>Powered by SEA-LION GUARD + Gemini</i>")
    lines.append("<i>This is an automated analysis. Use your own judgement.</i>")

    return "\n".join([l for l in lines if l is not None])


# ── Fact-Check via Research Agent ─────────────────────────────────────────────

async def fact_check_claims(
    claims: List[str],
    misinfo_result: Dict[str, Any],
    max_claims: int = 3,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Fact-check suspicious claims by researching them with the research_agent.

    Args:
        claims: List of suspicious claim strings from detect_misinformation.
        misinfo_result: Full misinformation detection result dict.
        max_claims: Maximum number of claims to research (bounds latency).
        timeout: Total timeout in seconds for all research tasks.

    Returns:
        Dict with: researched (bool), findings (list of dicts), error (str|None).
    """
    if not claims:
        return {"researched": False, "findings": [], "error": None}

    try:
        from research_agent import research as do_research
    except ImportError:
        logging.warning("[FactCheck] research_agent not available")
        return {"researched": False, "findings": [], "error": "research_agent not installed"}

    selected = claims[:max_claims]
    findings = []

    async def _research_one(claim: str) -> Dict[str, Any]:
        query = f"fact check: {claim}"
        try:
            result = await do_research(query)
            summary = ""
            if result.summary_path:
                try:
                    summary = Path(result.summary_path).read_text(encoding="utf-8")[:600]
                except Exception:
                    pass
            return {
                "claim": claim,
                "summary": summary or "No summary available.",
                "sources": result.sources[:5],
            }
        except Exception as exc:
            logging.exception(f"[FactCheck] Research failed for claim: {claim[:80]}")
            return {"claim": claim, "summary": f"Research unavailable: {exc}", "sources": []}

    try:
        tasks = [_research_one(c) for c in selected]
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
        for r in results:
            if isinstance(r, BaseException):
                logging.warning(f"[FactCheck] Task exception: {r}")
            else:
                findings.append(r)
    except asyncio.TimeoutError:
        logging.warning("[FactCheck] Research timed out after %.0fs", timeout)

    return {"researched": bool(findings), "findings": findings, "error": None}


def format_fact_check_section(fact_check_result: Dict[str, Any]) -> str:
    """
    Format fact-check findings as an HTML string for Telegram.

    Args:
        fact_check_result: Return value from fact_check_claims().

    Returns:
        HTML string, or empty string if nothing to show.
    """
    findings = fact_check_result.get("findings", [])
    if not findings:
        return ""

    lines = ["", "🔎 <b>Fact-Check</b>"]
    for i, f in enumerate(findings, 1):
        claim_safe = html.escape(f.get("claim", "")[:120])
        summary_safe = html.escape(f.get("summary", "")[:300])
        lines.append(f"<b>{i}. Claim</b>: <i>{claim_safe}</i>")
        lines.append(f"   {summary_safe}")
        sources = f.get("sources", [])
        if sources:
            src_links = ", ".join(html.escape(s) for s in sources[:3])
            lines.append(f"   📰 Sources: {src_links}")
        lines.append("")

    return "\n".join(lines)
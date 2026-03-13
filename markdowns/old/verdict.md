# prompt.md — AI Misinformation + Image Manipulation Detection

## Problem

The bot outputs inconclusive verdicts because of two root causes:

1. `run_guard_detection()` is failing silently — returning `label: "detection_failed"`
   which `run_insights()` receives as its input and has nothing real to analyse.

2. `run_insights()` receives the GUARD label string as `content` instead of the actual
   image/text content — so Gemini analyses the error string, not the real material.

3. No dedicated detection exists for:
   - AI misinformation (false claims, fabricated quotes, manipulated statistics)
   - Image manipulation (compositing, deepfakes, GAN artifacts)

---

## Root Cause Fix — `run_guard_detection()` in `tools.py`

Fix to: log the full raw response, broaden verdict parsing, and return specific fallback
labels (`"api_error"`, `"timeout"`, `"api_key_missing"`) instead of `"detection_failed"`.

```python
async def run_guard_detection(content: str, source_lang: str = "en") -> dict:
    """
    Run SEA-LION GUARD to detect if content is AI-generated.

    Always receives English-normalised text. Never raises — always returns a dict.

    Args:
        content: English text to analyse (max 2000 chars sent to API).
        source_lang: Original language of content (for logging only).

    Returns:
        dict: is_ai_generated (bool|None), confidence (float|None),
              label (str), raw_response (dict)
    """
    api_base = os.getenv("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
    api_key = os.getenv("OPENAI_API_KEY")
    guard_model = os.getenv("GUARD_MODEL", "aisingapore/SEA-LION-GUARD")

    if not api_key:
        logging.error("[GUARD] OPENAI_API_KEY not set")
        return {"is_ai_generated": None, "confidence": None,
                "label": "api_key_missing", "raw_response": {}}

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": guard_model,
        "messages": [{"role": "user", "content": content[:2000]}],
        "max_tokens": 256,
    }

    try:
        client = get_http_client()
        response = await asyncio.wait_for(
            client.post(f"{api_base}/chat/completions", json=payload, headers=headers),
            timeout=25.0
        )
        response.raise_for_status()
        data = response.json()
        raw_text = data["choices"][0]["message"]["content"].strip()
        logging.info(f"[GUARD] Raw response: {raw_text[:200]}")

        # Parse verdict — handle multiple response formats
        lower = raw_text.lower()
        if any(p in lower for p in ["ai-generated", "ai generated", "machine-generated", "llm-generated"]):
            is_ai, confidence = True, 0.85
        elif any(p in lower for p in ["human-generated", "human generated", "not ai", "written by human"]):
            is_ai, confidence = False, 0.85
        elif any(p in lower for p in ["inconclusive", "unclear", "uncertain", "cannot determine"]):
            is_ai, confidence = None, 0.5
        else:
            logging.warning(f"[GUARD] Unrecognised response format: {raw_text[:100]}")
            is_ai, confidence = None, 0.4

        return {
            "is_ai_generated": is_ai,
            "confidence": confidence,
            "label": raw_text,
            "raw_response": data,
        }

    except asyncio.TimeoutError:
        logging.error("[GUARD] Request timed out after 25s")
        return {"is_ai_generated": None, "confidence": None,
                "label": "timeout", "raw_response": {}}
    except Exception as e:
        logging.exception(f"[GUARD] Detection failed: {e}")
        return {"is_ai_generated": None, "confidence": None,
                "label": "api_error", "raw_response": {}}
```

---

## Feature 1 — AI Misinformation Detection

Add `detect_misinformation()` to `tools.py`.

Runs after GUARD and targets factual manipulation — false claims, fabricated quotes,
misleading statistics — that GUARD alone does not cover.

```python
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
    import google.generativeai as genai
    import json, re
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")

    source_context = f"Source context: {context_description}\n" if context_description else ""

    prompt = f"""
You are a fact-checking assistant specialised in detecting AI-assisted misinformation.

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
- Base assessment only on the content provided, not assumptions
"""

    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        raw = response.text.strip()
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(clean)
    except Exception as e:
        logging.exception(f"[Misinformation] Detection failed: {e}")
        return {
            "misinformation_detected": False,
            "misinformation_type": "unknown",
            "claims": [],
            "explanation": "Misinformation check unavailable.",
            "confidence": 0.0,
        }
```

---

## Feature 2 — Image Manipulation Detection

Add `detect_image_manipulation()` to `image_detector.py`.

Targets pixel-level and semantic manipulation that text-based GUARD cannot detect.

```python
async def detect_image_manipulation(file_path: str) -> dict:
    """
    Detect image manipulation, deepfakes, and AI generation artifacts using Gemini Vision.

    Targets: GAN-generated faces, compositing seams, cloning artifacts,
    unnatural lighting/shadows, and DALL-E/Midjourney/Stable Diffusion patterns.

    Args:
        file_path: Local path to image file.

    Returns:
        dict: manipulation_detected (bool), manipulation_type (str),
              signals (list[str]), explanation (str), confidence (float)
    """
    import google.generativeai as genai
    import json, re
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = """
You are an expert in digital image forensics and AI-generated content detection.

Analyse this image for signs of manipulation or AI generation.
Respond in JSON format only — no markdown, no preamble:

{
  "manipulation_detected": true or false,
  "manipulation_type": "none | deepfake_face | gan_generated | compositing | cloning | ai_art | unknown",
  "signals": ["list of specific visual signals observed, empty array if none"],
  "explanation": "one paragraph plain-language explanation",
  "confidence": 0.0 to 1.0
}

Check for:
1. Deepfake/face-swap: unnatural skin texture, blending at face edges, asymmetric features
2. GAN generation: overly smooth textures, background inconsistencies, repeating patterns
3. Compositing: mismatched lighting or shadows, perspective errors, edge artefacts
4. Cloning/inpainting: repeated textures, smeared regions, unnatural blurring
5. AI art patterns: DALL-E/Midjourney/Stable Diffusion visual signatures

Be conservative — only flag when clear visual evidence is present.
"""

    try:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
        response = await asyncio.to_thread(
            model.generate_content,
            [{"mime_type": "image/jpeg", "data": image_bytes}, prompt]
        )
        raw = response.text.strip()
        clean = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(clean)
    except Exception as e:
        logging.exception(f"[ImageManipulation] Detection failed: {e}")
        return {
            "manipulation_detected": False,
            "manipulation_type": "unknown",
            "signals": [],
            "explanation": "Image manipulation check unavailable.",
            "confidence": 0.0,
        }
```

---

## Feature 3 — Fix `run_insights()` to receive real content

Update `run_insights()` to accept `misinformation_result` and `manipulation_result`
as optional parameters, and build the Gemini prompt from the actual content — not the label.

```python
async def run_insights(content: str, detection_result: dict,
                       misinformation_result: dict = None,
                       manipulation_result: dict = None) -> dict:
    """
    Generate plain-language explanation combining all detection results.

    Args:
        content: The actual English-normalised content (NOT the GUARD label).
        detection_result: Output from run_guard_detection().
        misinformation_result: Output from detect_misinformation() — optional.
        manipulation_result: Output from detect_image_manipulation() — optional.

    Returns:
        dict: explanation (str), suggested_action (str), is_harmful (bool)
    """
    import google.generativeai as genai
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel("gemini-1.5-flash")

    guard_verdict = (
        "AI-generated" if detection_result.get("is_ai_generated") is True
        else "Human-generated" if detection_result.get("is_ai_generated") is False
        else "Inconclusive"
    )
    guard_label = detection_result.get("label", "unknown")

    # Skip GUARD context if it errored — don't pollute insights with error strings
    guard_context = ""
    if guard_label not in ("api_error", "timeout", "api_key_missing"):
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

    prompt = f"""
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

    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        explanation = response.text.strip()
        is_harmful = any(kw in explanation.lower() for kw in HARMFUL_KEYWORDS)
        return {"explanation": explanation, "suggested_action": "See explanation above.",
                "is_harmful": is_harmful}
    except Exception as e:
        return {"explanation": "Analysis unavailable.", "suggested_action": "Manual review recommended.",
                "is_harmful": False, "error": str(e)}
```

---

## Feature 4 — Wire all detections in `handle_photo` and `handle_text`

### `handle_photo` — run all three detections concurrently:

```python
# Run GUARD + misinformation + manipulation concurrently
detection_result, misinfo_result, manip_result = await asyncio.gather(
    run_guard_detection(combined_text, source_lang="en"),
    detect_misinformation(combined_text, context_description="image with OCR text"),
    detect_image_manipulation(file_path),
)

# Pass all results to insights
insights_result = await run_insights(
    combined_text,
    detection_result,
    misinformation_result=misinfo_result,
    manipulation_result=manip_result,
)
```

### `handle_text` — GUARD + misinformation only (no image manipulation):

```python
detection_result, misinfo_result = await asyncio.gather(
    run_guard_detection(english_text, source_lang="en"),
    detect_misinformation(english_text, context_description="text message"),
)

insights_result = await run_insights(
    english_text,
    detection_result,
    misinformation_result=misinfo_result,
)
```

---

## Output Format

Return four clearly labelled code blocks:

```python
# tools.py — updated run_guard_detection(), new detect_misinformation(), updated run_insights()
```

```python
# image_detector.py — new detect_image_manipulation()
```

```python
# telegram_bot.py — updated handle_photo() and handle_text() pipeline sections only
```

---

## Constraints

- `run_guard_detection()` must never return `label: "detection_failed"` — use
  `"api_error"`, `"timeout"`, or `"api_key_missing"` as specific fallback labels
- `detect_misinformation()` and `detect_image_manipulation()` must return structured
  dicts even on failure — never raise uncaught exceptions
- Gemini must respond in JSON — always strip markdown fences before parsing
- `run_insights()` must skip GUARD context when label is an error string
- `run_insights()` must handle `None` for both optional parameters
- All detections in `handle_photo` must use `asyncio.gather` — not sequential calls
- Do not change `format_detection_message()` or the ClickHouse schema
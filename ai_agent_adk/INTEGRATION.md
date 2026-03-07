# Feature Integration Prompt
## Translation Layer <> Detection Layer

---

## Reference Repository
https://github.com/NguiWeily/AI-Fake-Detector/tree/main

---

## Context

You are integrating two layers of a multimodal AI-generated content detection system:

**Translation Layer** (adk_agent/translator.py)
- SEA-LION Gemma 9B-IT subagent via Google ADK LlmAgent
- Supports: English, Mandarin (Simplified), Malay, Tamil, Singlish
- Called via AgentTool(agent=translator) from the root orchestrator
- Input: raw multilingual text + target language
- Output: translated text only (no preamble)

**Detection Layer** (from reference repo: image_detector.py, ocr.py, video_detector.py, tools.py)
- ocr.py: extracts raw text from images (may be non-English)
- image_detector.py: analyses image content for manipulation/AI-generation signals
- video_detector.py: samples video frames and generates textual descriptions
- tools.py -> run_guard_detection(): calls SEA-LION GUARD API on normalised text
- tools.py -> run_insights(): calls SEA-LION v4 to explain detection verdict

**Current gap**: The detection layer assumes English input. OCR output, video transcripts, and
user text are passed directly to GUARD without language normalisation. Detection verdicts and
insights are returned in English regardless of the user's language.

---

## Integration Architecture

```
[User Input - any language]
        |
        v
[Language Detection]  <- new: detect_language(text) -> ISO code
        |
        +-- If non-English --> [Translator Subagent]
        |                           SEA-LION Gemma 9B-IT
        |                           -> normalised English text
        |
        v
[Detection Layer]
   +-- OCR (image)      -> raw text  --> translate_to_english() if non-EN
   +-- Video frames     -> captions  --> translate_to_english() if non-EN
   +-- Plain text       -> passthrough if EN, else translate first
        |
        v
[SEA-LION GUARD]  <- always receives English input
        |
        v
[run_insights()]  <- generates English explanation
        |
        v
[Translator Subagent]  <- translate verdict + explanation -> user's language
        |
        v
[Telegram Bot Response - user's language]
```

---

## Task

Implement the following integration changes across the five files listed below.

---

### CHANGE 1: tools.py - Add language detection and translation bridge

Add three new functions:

**detect_language(text: str) -> str**
- Use the langdetect library (from langdetect import detect)
- Return ISO 639-1 language code (e.g. "en", "zh-cn", "ms", "ta")
- On failure, return "en" as a safe default
- Add docstring with args, returns, and exception behaviour

**async translate_to_english(text, source_lang, runner, user_id, session_id) -> str**
- Only translate if source_lang != "en"
- Call runner.run_async() with message: f"Translate the following {source_lang} text to English:\n{text}"
- Stream events and collect the final response text
- Return the translated English string
- On failure, return the original text unchanged (fail-safe)
- Add full docstring

**async translate_from_english(text, target_lang, runner, user_id, session_id) -> str**
- Only translate if target_lang != "en"
- Call runner.run_async() with message: f"Translate the following English text to {target_lang}:\n{text}"
- Stream events and collect the final response text
- Return the translated string
- On failure, return the original text unchanged (fail-safe)
- Add full docstring

**Update run_guard_detection()**:
- Add source_lang: str = "en" parameter
- Add a non-blocking warning log if source_lang != "en":
  print(f"[WARN] run_guard_detection received non-English input: {source_lang}")

---

### CHANGE 2: agent.py - Update orchestrator instruction for integrated flow

Update SYSTEM_INSTRUCTION to include the following section:

```
Translation-Detection Integration Rules:
1. Before calling run_guard_detection, always call detect_language on the input text.
2. If the detected language is not English, call translate_to_english first.
   Pass the translated English text to run_guard_detection and run_insights.
3. After receiving the verdict and explanation from run_insights, call
   translate_from_english to return the response in the user's original language.
4. For OCR output from images, always run detect_language on the extracted text
   before passing to run_guard_detection.
5. For video frame descriptions, treat them as English (generated internally) -
   no pre-translation needed. Translate only the final user-facing response.
6. Never pass non-English text directly to run_guard_detection.
```

---

### CHANGE 3: ocr.py - Add post-OCR language normalisation hook

After the OCR extraction step, add:

```python
# Post-OCR translation hook
# Caller (agent.py) is responsible for calling detect_language() and
# translate_to_english() on this output before passing to run_guard_detection.
# This function returns raw extracted text only - language-agnostic.
```

Add return type annotation: -> str (or -> dict when label_language=True)

Add optional parameter label_language: bool = False. When True, return:
  {"text": "extracted text here", "detected_lang": "zh-cn"}
When False (default), return the raw string as before.

---

### CHANGE 4: telegram_bot.py - Wrap all handlers with translation pipeline

For each message handler (handle_text, handle_photo, handle_audio, handle_video),
wrap the existing detection call with the following pattern:

```python
# Step 1: Extract raw content (existing logic unchanged)
raw_text = ...

# Step 2: Detect language
source_lang = detect_language(raw_text)

# Step 3: Translate to English if needed
english_text = await translate_to_english(raw_text, source_lang, runner, USER_ID, SESSION_ID)

# Step 4: Run detection on English text
detection_result = run_guard_detection(english_text, source_lang=source_lang)

# Step 5: Run insights on English text
insights = run_insights(english_text, detection_result)

# Step 6: Translate response back to user's language
final_response = await translate_from_english(
    insights["explanation"], source_lang, runner, USER_ID, SESSION_ID
)

# Step 7: Send response
await update.message.reply_text(final_response)
```

Do not change the extraction logic - only wrap the detection call sequence.

---

### CHANGE 5: translator.py - Extend TRANSLATOR_PROMPT for detection context

Append the following section to TRANSLATOR_PROMPT:

```
Detection Context Rules:
- When translating content FOR detection (non-English -> English):
  preserve all original phrasing, formatting, and punctuation exactly.
  Do not clean up grammar or fix errors - the detector needs authentic signals.

- When translating verdicts FOR users (English -> user language):
  translate naturally and clearly. Rephrase for cultural clarity where needed.
  Always preserve these English terms untranslated: "AI-generated", "deepfake",
  "confidence score", "GUARD", "OCR".

- For Singlish: translate to standard Singapore English, not British or American English.
```

---

## Output Format

Return five clearly labelled code blocks, one per changed file:

```python
# tools.py - new functions + updated run_guard_detection() only
```

```python
# agent.py - updated SYSTEM_INSTRUCTION string only
```

```python
# ocr.py - updated function signature and hook comment only
```

```python
# telegram_bot.py - updated handle_text handler as reference pattern
```

```python
# translator.py - updated TRANSLATOR_PROMPT string only
```

---

## Constraints

- Do not change the GUARD API call signature or ClickHouse schema
- Do not introduce new external dependencies beyond langdetect
- All new async functions must be compatible with Google ADK runner.run_async() pattern
- Fail-safe is mandatory: translation failures must never block detection
- The translator subagent must remain a separate LlmAgent - do not merge into root agent
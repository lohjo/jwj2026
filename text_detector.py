import os
from config import GEMINI_API_KEY, MODEL_NAME


def detect_fake_text(text: str) -> str:
    prompt = f"""
Analyze the following WhatsApp or Telegram message.

Determine:
- Is it misinformation?
- Does it look like a scam/hoax?
- Give fake probability (0-100%).

Message:
{text}
"""

    try:
        import google.genai as genai
    except ImportError as e:
        return f"Gemini provider not available: {e}"

    gemini_key = GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return "GEMINI_API_KEY not set in environment"

    def _extract_text(resp) -> str:
        """Extracts generated text from a Gemini API response."""
        if not resp:
            return ""
        # The primary way to get text from the new API is via `resp.text`
        if hasattr(resp, 'text') and isinstance(resp.text, str):
            return resp.text.strip()
        
        # Fallback for unexpected response structures
        if hasattr(resp, "candidates") and resp.candidates:
            candidate = resp.candidates[0]
            if hasattr(candidate, "content") and hasattr(candidate.content, "parts") and candidate.content.parts:
                return candidate.content.parts[0].text.strip()
        
        return f"Could not extract text from response: {resp}"

    try:
        genai.configure(api_key=gemini_key)
        
        # Use the modern GenerativeModel interface
        model_name = os.environ.get("MODEL_NAME", MODEL_NAME or "gemini-pro")
        model = genai.GenerativeModel(model_name)
        
        response = model.generate_content(prompt)
        
        return _extract_text(response)
        
    except Exception as e:
        # This will catch configuration errors, network issues, or API errors.
        return f"Gemini analysis error: {e}"

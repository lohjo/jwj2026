
# config.py — Single source of truth for ALL environment variables.
# No other file in this project should call os.getenv() directly.

from pathlib import Path
from dotenv import load_dotenv
import os
import sys

# Load .env from project root (or ai_agent_adk/ subfolder as fallback)
_project_root = Path(__file__).resolve().parent
_env_candidates = [
    _project_root / ".env",
    _project_root / "ai_agent_adk" / ".env",
]
for _p in _env_candidates:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)
        break


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        sys.exit(f"[SENTINEL] Missing required env var: {key}")
    return val


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _optional_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).upper() in ("1", "TRUE", "YES")


# ── Telegram ────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = _require("TELEGRAM_TOKEN")

# ── SEA-LION ────────────────────────────────────────────────────────────
SEALION_API_BASE = _optional("OPENAI_API_BASE", "https://api.sea-lion.ai/v1")
SEALION_API_KEY = _require("OPENAI_API_KEY")
GUARD_MODEL = _optional("GUARD_MODEL", "aisingapore/SEA-Guard")
SEALION_MODEL = _optional("MODEL", "aisingapore/Llama-SEA-LION-v3-70B-IT")
TRANSLATOR_MODEL = _optional("TRANSLATOR_MODEL", "aisingapore/Gemma-SEA-LION-v4-27B-IT")

# ── Primary LLM: Gemini ─────────────────────────────────────────────────
GEMINI_API_KEY = _require("GEMINI_API_KEY")
GEMINI_MODEL = _optional("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_LIVE_MODEL = _optional("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest")
GEMINI_LIVE_VOICE = _optional("GEMINI_LIVE_VOICE", "Aoede")
GOOGLE_CLOUD_PROJECT = _optional("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = _optional("GOOGLE_CLOUD_LOCATION", "asia-southeast1")
GOOGLE_GENAI_USE_VERTEXAI = _optional_bool("GOOGLE_GENAI_USE_VERTEXAI", False)

# ── Fallback LLM: Groq ──────────────────────────────────────────────────
GROQ_API_KEY = _optional("GROQ_API_KEY", "")
GROQ_MODEL = _optional("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_BASE = "https://api.groq.com/openai/v1"

# ── Speech ──────────────────────────────────────────────────────────────
DEEPGRAM_API_KEY = _optional("DEEPGRAM_API_KEY", "")
ELEVENLABS_API_KEY = _optional("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = _optional("ELEVENLABS_VOICE_ID", "")

# ── ClickHouse ──────────────────────────────────────────────────────────
CLICKHOUSE_HOST = _optional("CLICKHOUSE_HOST", "")
CLICKHOUSE_PORT = int(_optional("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER = _optional("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = _optional("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = _optional("CLICKHOUSE_DB", "agent_logs")
CLICKHOUSE_CONNECT_TIMEOUT = int(_optional("CLICKHOUSE_CONNECT_TIMEOUT", "10"))
CLICKHOUSE_SEND_RECEIVE_TIMEOUT = int(_optional("CLICKHOUSE_SEND_RECEIVE_TIMEOUT", "30"))
CLICKHOUSE_MAX_RETRIES = int(_optional("CLICKHOUSE_MAX_RETRIES", "1"))

# ── Research Agent ──────────────────────────────────────────────────────
FIRECRAWL_API_KEY = _optional("FIRECRAWL_API_KEY", "")
RESEARCH_DIR = Path(_optional("RESEARCH_DIR", "research"))

# ── Rate limiting ────────────────────────────────────────────────────────
COOLDOWN_SECONDS = float(_optional("COOLDOWN_SECONDS", "3.0"))

# ── Cloud Run ────────────────────────────────────────────────────────────
HEALTH_PORT = int(_optional("PORT", "8080"))

# ── Legacy aliases (used by existing code during migration) ──────────────
MODEL_NAME = GEMINI_MODEL


# ── SENTINEL Append Prompt (injected into every Claude SDK call) ─────────
SENTINEL_APPEND_PROMPT = """
## SENTINEL Behavioural Rules (Agent SDK Session)

### Output Format
- Always reply in the same language as the user's input — this is non-negotiable
- Use parse_mode HTML only — never MarkdownV2
- Verdict labels: ✅ Human-Written | 🤖 AI-Generated | ❓ Unclear | 🚨 AI + Harmful
- Harmful flag (🚨) only when is_ai_generated=True AND is_harmful=True simultaneously

### Code Generation Standards
- Return type: always a dict — never raise from detection or translation functions
- Async: all external I/O must be awaited or wrapped in asyncio.to_thread()
- Error handling: try/except around every external call, log to stderr, return fallback
- No blocking calls inside Telegram event loop handlers
- Use TypedDict or dataclass for all function signatures when adding new functions

### LLM Fallback Pattern
When generating code that calls an LLM:
1. Try Gemini first via pipeline/insights.py::call_llm()
2. On ANY exception (not just rate limits): fall back to Groq automatically
3. Set model_versions["llm_used"] = "gemini" | "groq" | "failed" in every ClickHouse row
4. Return "" on total failure — callers must handle empty string explicitly

### Detection Return Shape
Every detection function must return exactly this shape on failure — no exceptions:
```python
# run_guard_detection() fallback
{"is_ai_generated": None, "confidence": None, "label": "api_error", "raw_response": {}}

# detect_misinformation() fallback
{"misinformation_detected": False, "misinformation_type": "unknown",
 "claims": [], "explanation": "Unavailable.", "confidence": 0.0}

# detect_image_manipulation() fallback
{"manipulation_detected": False, "manipulation_type": "unknown",
 "signals": [], "explanation": "Unavailable.", "confidence": 0.0}
```

### ClickHouse Insert Rules
- Always use: settings={"async_insert": 1, "wait_for_async_insert": 0}
- Always call via: asyncio.to_thread(log_to_clickhouse, row_dict)
- log_to_clickhouse() must NEVER raise — swallow all exceptions, log to stderr

### Research Agent Rules
- Always check skill_cache before searching (similarity threshold: 0.80)
- Write to research/summaries/{YYYYMMDD}_{slug}.md after every run
- Write to research/skills/{slug}.md after every run
- Use Firecrawl /search endpoint — do NOT use raw httpx for page fetching
- onlyMainContent: true in all Firecrawl requests
"""

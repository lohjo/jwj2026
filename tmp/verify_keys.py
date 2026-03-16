"""Verify all API key connectivity — run from project root."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import json

from config import (
    SEALION_API_BASE, SEALION_API_KEY, GUARD_MODEL, TRANSLATOR_MODEL,
    GEMINI_API_KEY, GEMINI_MODEL,
    GROQ_API_KEY, GROQ_MODEL, GROQ_API_BASE,
    DEEPGRAM_API_KEY,
    ELEVENLABS_API_KEY,
    CLICKHOUSE_HOST, CLICKHOUSE_PORT, CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, CLICKHOUSE_DB,
)

PASS = "\033[92m✅ PASS\033[0m"
FAIL = "\033[91m❌ FAIL\033[0m"
SKIP = "\033[93m⏭️  SKIP\033[0m"

def check(name, fn):
    try:
        result = fn()
        if result is True:
            print(f"  {PASS}  {name}")
        elif result is None:
            print(f"  {SKIP}  {name} (key not set)")
        else:
            print(f"  {FAIL}  {name}: {result}")
    except Exception as e:
        print(f"  {FAIL}  {name}: {e}")


def verify_sealion_guard():
    if not SEALION_API_KEY:
        return None
    r = httpx.post(
        f"{SEALION_API_BASE.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {SEALION_API_KEY}", "Content-Type": "application/json"},
        json={"model": GUARD_MODEL, "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 16},
        timeout=15,
    )
    if r.status_code == 200:
        return True
    return f"HTTP {r.status_code}: {r.text[:200]}"


def verify_sealion_translator():
    if not SEALION_API_KEY:
        return None
    r = httpx.post(
        f"{SEALION_API_BASE.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {SEALION_API_KEY}", "Content-Type": "application/json"},
        json={"model": TRANSLATOR_MODEL, "messages": [{"role": "user", "content": "Translate: Hello"}], "max_tokens": 16},
        timeout=15,
    )
    if r.status_code == 200:
        return True
    return f"HTTP {r.status_code}: {r.text[:200]}"


def verify_gemini():
    if not GEMINI_API_KEY or GEMINI_API_KEY.lower().startswith("your_"):
        return None
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents="Say hello", config={"max_output_tokens": 16})
    if resp.text and resp.text.strip():
        return True
    return "Empty response"


def verify_groq():
    if not GROQ_API_KEY:
        return None
    r = httpx.post(
        f"{GROQ_API_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
        json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": "Say hello"}], "max_tokens": 16},
        timeout=15,
    )
    if r.status_code == 200:
        return True
    return f"HTTP {r.status_code}: {r.text[:200]}"


def verify_deepgram():
    if not DEEPGRAM_API_KEY:
        return None
    r = httpx.get(
        "https://api.deepgram.com/v1/projects",
        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
        timeout=10,
    )
    if r.status_code == 200:
        return True
    return f"HTTP {r.status_code}: {r.text[:200]}"


def verify_elevenlabs():
    if not ELEVENLABS_API_KEY:
        return None
    r = httpx.get(
        "https://api.elevenlabs.io/v1/user",
        headers={"xi-api-key": ELEVENLABS_API_KEY},
        timeout=10,
    )
    if r.status_code == 200:
        return True
    return f"HTTP {r.status_code}: {r.text[:200]}"


def verify_clickhouse():
    if not CLICKHOUSE_HOST or not CLICKHOUSE_PASSWORD:
        return None
    try:
        import clickhouse_connect
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST, port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER, password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB, secure=True, connect_timeout=5,
        )
        result = client.query("SELECT 1")
        client.close()
        return True
    except Exception as e:
        return str(e)


if __name__ == "__main__":
    print("\n🔑 SENTINEL API Key Verification\n")

    print("── SEA-LION ──")
    check(f"GUARD ({GUARD_MODEL})", verify_sealion_guard)
    check(f"Translator ({TRANSLATOR_MODEL})", verify_sealion_translator)

    print("\n── LLM ──")
    check(f"Gemini ({GEMINI_MODEL})", verify_gemini)
    check(f"Groq ({GROQ_MODEL})", verify_groq)

    print("\n── Speech ──")
    check("Deepgram", verify_deepgram)
    check("ElevenLabs", verify_elevenlabs)

    print("\n── Database ──")
    check(f"ClickHouse ({CLICKHOUSE_HOST})", verify_clickhouse)

    print()

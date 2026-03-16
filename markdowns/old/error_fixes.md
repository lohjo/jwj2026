# SENTINEL — Error Fixes

## Summary

| # | Error | Severity | Status | Fix |
|---|-------|----------|--------|-----|
| 1 | Wrong Gemini package (`google.generativeai`) | P0 | Causing fallback to Groq | Replace import + update all calls |
| 2 | Invalid Gemini API key (400) | P0 | Causing fallback to Groq | Regenerate key at aistudio.google.com |
| 3 | SEA-LION 401 Unauthorized | P1 | GUARD failing, translation falling back | Fix `OPENAI_API_KEY` in `.env` |
| 4 | ClickHouse connection timeout | P2 | Logging silently failing | Resume instance + whitelist IP |

---

## Error 1 — Wrong Gemini Package

**File:** `pipeline/insights.py`, line 10

**Error message:**
```
All support for the `google.generativeai` package has ended.
```

**Cause:** The deprecated `google-generativeai` package is still being imported. It no longer receives updates or bug fixes.

**Fix — update the import:**

```python
# ❌ WRONG — dead package
import google.generativeai as genai

# ✅ CORRECT — new package
from google import genai
```

**Fix — update every Gemini call in the file:**

```python
# ❌ WRONG — old pattern
genai.configure(api_key=...)
model = genai.GenerativeModel("gemini-1.5-flash")
response = model.generate_content(prompt)

# ✅ CORRECT — new pattern
client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=prompt
)
text = response.text
```

**Fix — update packages:**

```bash
.venv\Scripts\pip install google-genai
.venv\Scripts\pip uninstall google-generativeai
```

---

## Error 2 — Invalid Gemini API Key (400)

**Error message:**
```
Gemini failed (reason=api_key_invalid, error=400 API key not valid)
```

**Cause:** The `GEMINI_API_KEY` in `.env` is wrong, expired, or belongs to a Google Cloud project that does not have the Generative Language API enabled.

> **Note:** Groq fallback is working (`llm_used=groq, response='SENTINEL_OK'`) — `GROQ_API_KEY` is fine.

**Fix:**

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey) and generate a fresh key
2. Paste it into `.env`:

```env
GEMINI_API_KEY=AIza...your_real_key_here
```

3. Confirm the key has **Generative Language API** enabled in Google Cloud Console

4. Verify it loads correctly:

```bash
.venv\Scripts\python.exe -c "from config import GEMINI_API_KEY; print(GEMINI_API_KEY[:8])"
```

---

## Error 3 — SEA-LION 401 Unauthorized

**Affected:** GUARD detection + translation

**Error messages:**
```
[GUARD] Unauthorized (401). Check OPENAI_API_KEY for SEA-LION.
SEA-LION translation failed: Client error '401 Unauthorized' for url
'https://api.sea-lion.ai/v1/chat/completions'
```

**Cause:** `OPENAI_API_KEY` in `.env` is missing, wrong, or expired for the SEA-LION API endpoint.

> **Note:** Translation showing `[PASS]` with `detected=zh` is expected — the fallback correctly returned the original text rather than crashing, per `CLAUDE.md` rules.

**Fix:**

1. Get a valid key from the [AI Singapore portal](https://sea-lion.ai)
2. Update `.env`:

```env
OPENAI_API_KEY=your_sealion_api_key_here
OPENAI_API_BASE=https://api.sea-lion.ai/v1
```

3. Verify the key works:

```bash
.venv\Scripts\python.exe -c "
import httpx, os
from dotenv import load_dotenv
load_dotenv(override=True)
r = httpx.get(
    'https://api.sea-lion.ai/v1/models',
    headers={'Authorization': f'Bearer {os.getenv(\"OPENAI_API_KEY\")}'}
)
print(r.status_code)
"
```

Should return `200`. If still `401`, the key is wrong or inactive.

---

## Error 4 — ClickHouse Connection Timeout

**Error message:**
```
Connection to e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud timed out (port 8123)
[FAIL] clickhouse (20.50s): {'status': 'failed', 'error': 'ClickHouse client unavailable'}
```

**Cause:** The TCP connection to ClickHouse Cloud is timing out before any HTTP request is made. Two likely causes: the free-tier instance has auto-paused, or your current IP is not on the allowlist.

**Fix — work through in order:**

**Step 1 — Check if the instance is paused**

Log into [clickhouse.cloud](https://clickhouse.cloud), find service `e8vpdqdapz`, and click **Resume** if it shows that option. Free-tier instances auto-pause after inactivity.

**Step 2 — Whitelist your current IP**

```bash
# Find your public IP
curl https://api.ipify.org
```

Then in ClickHouse Cloud → your service → **Security → Allowed IPs**, add that IP.

**Step 3 — Test connectivity after whitelisting**

```bash
.venv\Scripts\python.exe verify_clickhouse.py
```

Expected output: `Result: 1`

**Step 4 — Check for network/VPN blocking**

If port 8123 outbound is blocked by a VPN or corporate firewall, test on a mobile hotspot to confirm. If that works, the network is the issue.

---

## Quick Reference — `.env` Keys to Check

```env
GEMINI_API_KEY=          # regenerate at aistudio.google.com/apikey
OPENAI_API_KEY=          # SEA-LION key from AI Singapore portal
OPENAI_API_BASE=https://api.sea-lion.ai/v1
GROQ_API_KEY=            # ✅ working — no action needed
CLICKHOUSE_HOST=e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud
CLICKHOUSE_PORT=8123
```
# CLAUDE CODE — PLANNING PROMPT
# SENTINEL: ClickHouse Schema + Web Research Subagent

---

## PHASE 0 — VERIFY CONNECTIVITY

Before writing any code, confirm the ClickHouse connection is live.
Run the following verification script and assert it prints `Result: 1`.
If the connection fails, stop and surface the exact error — do not proceed.

```python
import clickhouse_connect

if __name__ == '__main__':
    client = clickhouse_connect.get_client(
        host='e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud',
        user='default',
        password='Y1JF.jPt_rb8o',
        secure=True
    )
    print("Result:", client.query("SELECT 1").result_set[0][0])
```

Expected output: `Result: 1`

---

## PHASE 1 — SQL ASSISTANT PROMPT (ClickHouse Schema Design)

> Hand this prompt verbatim to a SQL AI assistant (e.g. Claude, ChatGPT, or
> ClickHouse's own SQL editor assistant).

---

### PROMPT FOR SQL ASSISTANT

You are a ClickHouse schema architect. Design a production-ready table for a
**multimodal AI content detection system** called SENTINEL running on
ClickHouse Cloud (asia-southeast1).

#### Connection details (already verified)
```
host:     e8vpdqdapz.asia-southeast1.gcp.clickhouse.cloud
user:     default
database: agent_logs
secure:   true (port 8443)
```

#### Reference documentation
- ClickHouse docs: https://clickhouse.com/docs
- Real-time analytics for AI/LLM workloads: https://learn.clickhouse.com/visitor_catalog_class/show/1872073
- Workshop slides: https://drive.google.com/file/d/16Sq6bPpiDoKMwXWomdEcgudoagI48xOy/view

#### Requirements

**Table name:** `detection_events`

**Must store — one row per detection request:**

| Field | Type | Notes |
|---|---|---|
| event_id | UUID | Auto-generated |
| timestamp | DateTime64(3) | Millisecond precision, server default |
| user_id | String | Telegram user ID (hashed) |
| session_id | String | Per-conversation session key |
| content_type | Enum | `'text' \| 'image' \| 'audio' \| 'video'` |
| source_language | LowCardinality(String) | ISO 639-1 code, e.g. `'zh'`, `'ms'` |
| content_preview | String | First 500 chars / OCR excerpt / transcript excerpt |
| guard_label | String | Raw SEA-LION GUARD response |
| guard_verdict | Enum | `'ai_generated' \| 'human_generated' \| 'inconclusive' \| 'error'` |
| guard_confidence | Nullable(Float32) | 0.0–1.0 |
| misinfo_detected | Bool | From `detect_misinformation()` |
| misinfo_type | LowCardinality(String) | e.g. `'fabricated_quote'`, `'none'` |
| manipulation_detected | Bool | From `detect_image_manipulation()` |
| manipulation_type | LowCardinality(String) | e.g. `'deepfake_face'`, `'none'` |
| explanation | String | Final plain-language explanation shown to user |
| is_harmful | Bool | Combined harm flag |
| processing_ms | UInt32 | End-to-end latency in milliseconds |
| model_versions | Map(String, String) | e.g. `{'guard': 'SEA-LION-GUARD', 'llm': 'gemini-1.5-flash'}` |
| error_code | LowCardinality(String) | `'none'` or specific error key |

**Design constraints:**

1. **Column-oriented storage** — use `MergeTree` family engine. Justify your choice
   of `MergeTree` vs `ReplacingMergeTree` vs `SummingMergeTree` for this use case.

2. **Async-safe inserts** — the Python client must be able to fire-and-forget rows
   using `async_insert=1` and `wait_for_async_insert=0` so the Telegram bot handler
   is never blocked. Include the required ClickHouse settings in the INSERT call.

3. **Ordering key** — optimise for queries like:
   - "All detections by user in last 7 days"
   - "All `ai_generated` verdicts this hour"
   - "Aggregate misinfo detections by language this week"
   Choose `ORDER BY` accordingly and explain the tradeoff.

4. **Partitioning** — partition by month (`toYYYYMM(timestamp)`) for cheap TTL drops.

5. **TTL** — raw rows expire after 90 days. Summarised aggregates (see below) kept
   forever.

6. **Materialized view** — create a companion `detection_hourly_stats` materialized
   view that pre-aggregates per hour:
   - total events
   - count by `guard_verdict`
   - count by `content_type`
   - average `processing_ms`
   - count of `is_harmful = true`

7. **Python insert helper** — write a `log_to_clickhouse()` function using
   `clickhouse-connect` (not `clickhouse-driver`) that:
   - Accepts a dict matching the schema above
   - Uses `client.insert()` with `settings={'async_insert': 1, 'wait_for_async_insert': 0}`
   - Never raises — wraps in try/except and logs errors to stderr
   - Is safe to call with `asyncio.to_thread(log_to_clickhouse, row_dict)` from
     an async Telegram handler

**Output format:**
Return four clearly labelled blocks:
```sql
-- 1. CREATE TABLE detection_events
```
```sql
-- 2. CREATE MATERIALIZED VIEW detection_hourly_stats
```
```python
# 3. log_to_clickhouse() Python function
```
```markdown
# 4. Schema design rationale (MergeTree choice, ORDER BY, partitioning)
```

---

## PHASE 2 — WEB RESEARCH SUBAGENT

Design and implement a `research_agent/` subagent that:

### 2a. Core behaviour

When given a user query (e.g. `"How does SEA-LION GUARD score text?"`), the agent:

1. **Searches** the web using SearXNG (env: `SEARXNG_URL`) for the top 5–10 results
2. **Fetches** each result URL with `httpx` (async, 15s timeout, max 50KB per page)
3. **Extracts** clean text — strip HTML tags, nav, footers, ads (use `trafilatura`)
4. **Deduplicates** — skip pages with < 200 words or cosine similarity > 0.85 to
   an already-seen page (use sentence-transformers `all-MiniLM-L6-v2`)
5. **Summarises** — calls SEA-LION v4 / Gemini to produce a structured `.md` summary
6. **Saves** output to the folder structure below

### 2b. Output folder structure

```
research/
├── raw/
│   └── {YYYYMMDD}_{slug}/
│       ├── 01_{domain}.txt       # raw extracted text per source
│       ├── 02_{domain}.txt
│       └── metadata.json         # URLs, fetch timestamps, word counts
├── summaries/
│   └── {YYYYMMDD}_{slug}.md      # structured summary for human reading
└── skills/
    └── {topic_slug}.md           # distilled "skill card" — model reference doc
```

### 2c. Skills file format

A skill card is a **model-facing reference document** — not a human summary.
It must follow this exact template so the agent can read it instead of re-searching:

```markdown
---
topic: {topic}
last_updated: {ISO date}
sources: [{url1}, {url2}]
confidence: high | medium | low
---

# {Topic Title}

## Key Facts
- Bullet-point distilled facts only — no filler prose

## Code Patterns
```{language}
# Minimal working example if applicable
```

## Gotchas
- Known failure modes, edge cases, version-specific behaviour

## Do Not Search Again If
- Conditions under which this skill is sufficient to answer the query
  without re-fetching (e.g. "SEA-LION GUARD API has not changed since v3")
```

### 2d. Skill cache lookup

Before searching the web, the agent must:
1. `ls research/skills/` and load all `.md` frontmatter
2. Embed the user query with `all-MiniLM-L6-v2`
3. Compare against cached skill topic embeddings
4. If similarity > 0.80 → return cached skill, skip web search
5. If similarity 0.60–0.80 → use cached skill AND do a targeted "update search"
   limited to results newer than `last_updated`
6. If similarity < 0.60 → full web search

### 2e. Agent interface

```python
# research_agent/agent.py

async def research(query: str, force_refresh: bool = False) -> ResearchResult:
    """
    Main entrypoint.

    Args:
        query: Natural language research question.
        force_refresh: Skip skill cache even if hit found.

    Returns:
        ResearchResult(
            summary_path: str,       # path to .md summary
            skill_path: str,         # path to skill card
            cache_hit: bool,         # was skill cache used?
            sources: list[str],      # URLs used
            raw_dir: str             # path to raw/ subfolder
        )
    """
```

### 2f. Integration with SENTINEL Telegram bot

Add a `/research <query>` Telegram command that:
1. Calls `research_agent.research(query)`
2. Replies with the first 800 chars of the summary + a file attachment of the full `.md`
3. Logs the research event to ClickHouse (`content_type = 'text'`, `guard_verdict = 'human_generated'` since it is a bot-initiated lookup)

### 2g. Dependencies

Add to `requirements.txt`:
```
trafilatura>=1.8
sentence-transformers>=3.0
httpx>=0.27
numpy>=1.26
```

---

## PHASE 3 — DELIVERABLES CHECKLIST

Claude Code must produce these files in order:

```
[ ] verify_clickhouse.py              # Phase 0 connectivity test
[ ] sql/01_create_table.sql           # detection_events DDL
[ ] sql/02_create_mv.sql              # materialized view DDL
[ ] tools.py (updated)               # log_to_clickhouse() with async_insert
[ ] research_agent/__init__.py
[ ] research_agent/agent.py           # research() entrypoint
[ ] research_agent/fetcher.py         # httpx fetch + trafilatura extraction
[ ] research_agent/deduplicator.py   # embedding + cosine similarity cache
[ ] research_agent/summariser.py     # SEA-LION / Gemini summarisation calls
[ ] research_agent/skill_cache.py    # skill lookup + frontmatter parsing
[ ] telegram_bot.py (updated)        # /research command handler
[ ] requirements.txt (updated)
```

---

## CONSTRAINTS

- Never block the Telegram event loop — all I/O must be `await`ed or wrapped in
  `asyncio.to_thread()`
- ClickHouse inserts must use `async_insert=1` — no synchronous blocking inserts
- Skill cache must be checked before every web search — not optional
- `log_to_clickhouse()` must never raise — swallow all exceptions, log to stderr
- All file paths relative to project root; never use absolute paths in code
- Do not install `clickhouse-driver` — use `clickhouse-connect` exclusively
- Python minimum version: 3.11
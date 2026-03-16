# Apply Workshop Best Practices

Apply patterns from the Google Multimodal Agent Workshop (way-back-home repo:
https://github.com/lohjo/way-back-home) to SENTINEL. These are production-grade
patterns validated across 6 progressive workshop levels using Google ADK,
Cloud Run, and multi-agent architectures.

Run this command when: adding a new agent, refactoring the detection pipeline,
improving Cloud Run performance, or auditing Docker/Cloud Build configuration.

---

## Pattern 1 — `before_agent_callback`: Pre-Hydrate Agent State

**Source**: way-back-home Level 1 `agent.py`

**Apply when**: SENTINEL's ADK runner (`pipeline/sdk_runner.py`) initialises
a new agent session. All participant/session context should be fetched **once**
here, not inside individual tools or sub-agents.

**Audit check**:
```
[ ] sdk_runner.py uses before_agent_callback to pre-fetch session context
[ ] Callback sets state keys: user_id, session_id, source_lang, backend_url
[ ] Sub-agents reference these via {key} state templating in instructions
[ ] No sub-agent independently calls os.getenv() or makes config API calls
```

**Implementation pattern**:
```python
# pipeline/sdk_runner.py
from google.adk.agents.callback_context import CallbackContext
import httpx

async def setup_sentinel_context(callback_context: CallbackContext) -> None:
    """
    Fetch all session context once before any agent runs.
    Populates state so sub-agents get context from {key} templating,
    not from redundant tool calls.
    """
    user_id = callback_context.state.get("user_id", "anonymous")
    callback_context.state["backend_url"] = BACKEND_URL
    callback_context.state["source_lang"] = callback_context.state.get("source_lang", "en")
    callback_context.state["cooldown_seconds"] = COOLDOWN_SECONDS
    # Add any per-session context here — fetched once, shared everywhere

root_agent = Agent(
    name="SentinelRoot",
    ...,
    before_agent_callback=setup_sentinel_context,
)
```

**Benefit**: Reduces token usage. Context injected via `{key}` in instructions
costs zero extra API calls vs each sub-agent independently discovering its inputs.

---

## Pattern 2 — `{key}` State Templating: Zero-cost Context Injection

**Source**: way-back-home Level 1 sub-agents

**Apply when**: Writing system prompts/instructions for any SENTINEL ADK agent.
Never hardcode values or have agents call tools just to discover their own inputs.

**Audit check**:
```
[ ] Sub-agent instructions use {source_lang}, {user_id}, {content_preview}
    from state rather than passing these through tool arguments
[ ] Tool signatures only include parameters the LLM must actually reason about
    (not operational params like user_id, backend_url, session_id)
```

**Example for SENTINEL**:
```python
# pipeline/detector.py (if using ADK agents)
guard_agent = Agent(
    name="GuardAgent",
    instruction="""
    You are SENTINEL's content guard.
    User language: {source_lang}
    Content to analyse (already translated to English):
    {english_content}

    Call run_guard_detection with the content above.
    Return your verdict as a structured dict.
    """,
)
# {source_lang} and {english_content} are injected from state —
# the agent never wastes tokens figuring out what to analyse.
```

---

## Pattern 3 — `ToolContext`: State Access Without LLM Intermediation

**Source**: way-back-home `confirm_tools.py`

**Apply when**: Any SENTINEL tool needs user_id, session_id, or config values.
Pass only the semantically meaningful parameter to the LLM; let ToolContext
inject the operational ones automatically.

**Audit check**:
```
[ ] log_to_clickhouse() and similar tools accept ToolContext as parameter
[ ] ToolContext reads user_id, session_id from state — not from LLM output
[ ] Tool function signatures exposed to the LLM are as minimal as possible
```

**Example**:
```python
# pipeline/logger.py (ADK tool variant)
from google.adk.tools import ToolContext

def log_detection_result(
    verdict: str,          # ← LLM provides this
    confidence: float,     # ← LLM provides this
    tool_context: ToolContext,  # ← ADK injects automatically
) -> dict:
    user_id = tool_context.state.get("user_id", "anonymous")
    session_id = tool_context.state.get("session_id", "")
    # user_id never appears in the LLM's tool call — reduces hallucination risk
    log_to_clickhouse({"user_id": user_id, "verdict": verdict, ...})
    return {"logged": True}
```

---

## Pattern 4 — `ParallelAgent`: Concurrent Independent Work

**Source**: way-back-home Level 1 `EvidenceAnalysisCrew`

**Apply when**: SENTINEL runs guard + misinfo + manipulation detection.
These three are **already concurrent** via `asyncio.gather`. If migrating to
ADK agents, use `ParallelAgent` instead.

**Audit check**:
```
[ ] pipeline/detector.py uses asyncio.gather for guard + misinfo + manipulation
    (not sequential awaits)
[ ] If ADK agents are used: ParallelAgent wraps the three detection specialists
[ ] 2-of-3 consensus applied for final verdict when detectors disagree
```

**ADK migration pattern** (if moving detection into ADK agents):
```python
from google.adk.agents import ParallelAgent

detection_crew = ParallelAgent(
    name="DetectionCrew",
    sub_agents=[guard_agent, misinfo_agent, manipulation_agent],
)
# Runs all three concurrently — ~3s instead of ~9s sequential
```

---

## Pattern 5 — Docker: Layer Caching + Non-root + Health Check

**Source**: way-back-home gold-standard Dockerfile

**Apply when**: Modifying `Dockerfile` for Cloud Run deployment.

**Audit check**:
```
[ ] requirements.txt copied and pip install run BEFORE copying app code
    (so pip layer is cached until requirements change — not every code change)
[ ] --no-cache-dir on pip install
[ ] apt-get install uses --no-install-recommends + rm -rf /var/lib/apt/lists/*
[ ] Non-root user created: useradd --create-home appuser + USER appuser
[ ] HEALTHCHECK directive present
[ ] PYTHONDONTWRITEBYTECODE=1 and PYTHONUNBUFFERED=1 set
[ ] python:3.11-slim base image (not full python:3.11)
```

**Gold standard Dockerfile for SENTINEL**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Layer caching: deps first, app code second
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Security: non-root user
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

ENV PORT=8080
CMD ["python", "telegram_bot.py"]
```

---

## Pattern 6 — Cloud Build: Dual Tagging + Selective Deploy Flags

**Source**: way-back-home `cloudbuild.yaml`

**Apply when**: Modifying `cloudbuild.yaml` for SENTINEL's CI/CD pipeline.

**Audit check**:
```
[ ] Every image tagged with both ${BUILD_ID} (immutable) and latest (mutable)
[ ] _DEPLOY_BACKEND substitution variable allows skipping deploy step
[ ] Cloud Run service labeled with app=sentinel, component=backend
[ ] Uses Artifact Registry (asia-southeast1-docker.pkg.dev) not legacy gcr.io
```

**Pattern**:
```yaml
# cloudbuild.yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    id: build
    args:
      - build
      - -t
      - asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:${BUILD_ID}
      - -t
      - asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:latest
      - .

  - name: 'gcr.io/cloud-builders/docker'
    id: push
    waitFor: ['build']
    args: ['push', '--all-tags',
           'asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app']

  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    id: deploy
    waitFor: ['push']
    entrypoint: bash
    args:
      - -c
      - |
        if [[ "${_DEPLOY_BACKEND}" == "true" ]]; then
          gcloud run deploy sentinel \
            --image=asia-southeast1-docker.pkg.dev/$PROJECT_ID/sentinel/app:${BUILD_ID} \
            --region=asia-southeast1 \
            --labels=app=sentinel,component=backend
        fi

substitutions:
  _DEPLOY_BACKEND: 'true'
```

---

## Pattern 7 — Config Resolution: Local + Cloud Portability

**Source**: way-back-home `config_utils.py`

**Apply when**: SENTINEL code needs to run both locally and on Cloud Run
without any changes.

**Audit check**:
```
[ ] config.py reads env vars first (Cloud Run path)
[ ] config.py falls back to .env file for local dev (via load_dotenv)
[ ] No hardcoded paths — uses Path(__file__).resolve().parent for relative paths
[ ] Same codebase works: local .venv, Cloud Shell, Cloud Run
```

SENTINEL's `config.py` already follows this — confirm `load_dotenv(override=True)`
is present and `_require()` / `_optional()` functions are used consistently.

---

## Pattern 8 — Idempotent Infrastructure Script

**Source**: way-back-home `setup-infrastructure.sh`

**Apply when**: Creating or updating the GCP setup script for SENTINEL.

**Audit check**:
```
[ ] setup-gcp.sh exists at project root
[ ] Script enables all required GCP APIs
[ ] Script creates IAM bindings for Cloud Build and Cloud Run service accounts
[ ] Every create operation checks for pre-existence first (idempotent)
[ ] Script is safe to re-run without side effects
```

**Template**:
```bash
#!/bin/bash
set -euo pipefail

PROJECT_ID=$(gcloud config get-value project)
REGION="asia-southeast1"

echo "=== Enabling GCP APIs ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJECT_ID"

echo "=== Creating Artifact Registry (idempotent) ==="
gcloud artifacts repositories describe sentinel \
  --location="$REGION" --project="$PROJECT_ID" &>/dev/null \
  || gcloud artifacts repositories create sentinel \
       --repository-format=docker \
       --location="$REGION" \
       --project="$PROJECT_ID"

echo "=== Done. Re-run any time — all operations are idempotent. ==="
```

---

## Summary: Apply to SENTINEL

Run through these in order when doing a pipeline or deployment refactor:

| Pattern | File to check | Key question |
|---|---|---|
| `before_agent_callback` | `pipeline/sdk_runner.py` | Is context fetched once and shared via state? |
| `{key}` templating | All ADK agent instructions | Do agents use state injection instead of tool discovery? |
| `ToolContext` | Any tool that needs user_id | Do tools read operational params from state, not LLM? |
| `ParallelAgent` | `pipeline/detector.py` | Are guard + misinfo + manipulation concurrent? |
| Docker best practices | `Dockerfile` | Layer caching, non-root, health check all present? |
| Cloud Build dual tagging | `cloudbuild.yaml` | Both BUILD_ID and latest tags? Artifact Registry not gcr.io? |
| Config resolution | `config.py` | load_dotenv + env var priority working locally and on Cloud Run? |
| Idempotent infra | `setup-gcp.sh` | Safe to re-run? All APIs and IAM roles covered? |

## Arguments

$ARGUMENTS


---

## Functionalities

**Overall Purpose**: An immersive, gamified AI workshop platform where participants learn Google Cloud AI technologies by rescuing a stranded space explorer across 6 progressive levels.

| Level | Mission | AI Skills Taught |
|-------|---------|-----------------|
| **Level 0** | Generate explorer identity/avatar | Multi-turn image generation (Gemini 2.5 Flash Image), chat session consistency |
| **Level 1** | Pinpoint crash location | Multi-agent systems (Google ADK), MCP servers (custom + managed BigQuery), `ParallelAgent`, `before_agent_callback`, state templating, multimodal video (Veo 3.1) |
| **Level 2** | Process SOS signals (Survivor Network) | Graph-based analytics (Cloud Spanner property graphs), hybrid search (semantic + keyword), media extraction pipeline, Memory Bank, Agent Engine deployment |
| **Level 3** | Biometric scanner challenge | Real-time WebSocket with Gemini Live, audio/video streaming, hand gesture recognition |
| **Level 4** | Ship engine assembly | Screen sharing via `getDisplayMedia()`, drag-and-drop game, Redis data structures, A2A SDK |
| **Level 5** | Satellite formation control | A2A over Kafka, Server-Sent Events (SSE), formation orchestration agent |

**Dashboard** (shared across all levels):
- **Backend**: FastAPI + Firestore + Firebase Storage + Firebase Auth (admin). Manages events, participants, avatars, evidence, level progress.
- **Frontend**: Next.js 14 + React Three Fiber 3D interactive planet map showing all participants, with real-time polling, keyboard shortcuts, and social sharing.
- **Helper**: HTML tool for generating Firebase ID tokens for admin API testing.

---

## Inner Workings

### Core Architecture Flow
1. **setup.sh** authenticates, validates event codes via API, reserves a username/participant_id, writes config.json to project root
2. **Level 0**: User implements `generate_explorer_avatar()` in generator.py (stub); `create_identity.py` orchestrates generation → upload → registration
3. **Level 1**: `generate_evidence.py` creates biome-specific soil/flora/star evidence using Gemini + Veo. Then 3 specialist ADK agents (geological, botanical, astronomical) run in parallel via `ParallelAgent`, each using different MCP patterns, with 2-of-3 consensus to confirm location
4. **Level 2**: Full-stack app with Spanner graph DB, multimedia extraction pipeline (`SequentialAgent` with 4 stages), hybrid search tools, and optional Memory Bank via Agent Engine
5. **Levels 3-5**: Real-time interactive games using WebSocket streaming, Gemini Live, Redis, Kafka A2A

### Key Patterns
- **Config propagation**: config.json at project root → environment variables via set_env.sh → `before_agent_callback` fetches from backend API for Cloud Run
- **`config_utils.py`** (Level 1): Unified config resolution - env vars (Cloud Run) → local file search upward
- **Biome mapping**: Planet divided into 4 quadrants (NW=CRYO, NE=VOLCANIC, SW=BIOLUMINESCENT, SE=FOSSILIZED) based on coordinates
- **Workshop-as-code**: `#REPLACE` / `#TODO` placeholders are intentional — participants fill these in using codelabs

### Deployment
- cloudbuild.yaml (top-level): Builds and deploys dashboard backend + frontend to Cloud Run via Artifact Registry
- cloudbuild.yaml: Deploys custom MCP server as separate Cloud Run service
- cloudbuild.yaml: Deploys Level 2 backend + frontend pair
- Levels 3-5: Use Dockerfiles in solutions for multi-stage builds (Node frontend → Python backend)

---

## Obsolete Code / Files

### Confirmed Redundancies

1. **`billing-enablement.py` duplicated 6 times** — Identical copies exist in billing-enablement.py, billing-enablement.py, billing-enablement.py, billing-enablement.py, billing-enablement.py, and billing-enablement.py. A separate variant exists in billing-enablement.py using gcloud interactively. Could be consolidated into a shared module.

2. **`init.sh` duplicated** — init.sh and init.sh are identical GCP project setup scripts.

3. **Duplicate `MCP_SERVER_URL` in set_env.sh** — Line `export MCP_SERVER_URL=...` appears twice at the end of the file (identical value).

4. **App.css** — Default Vite boilerplate CSS, not customized. All actual styling is in index.css and Tailwind classes.

5. **config_utils.py** — Appears to be an exact duplicate of config_utils.py (the solutions version adds no additional implementation since config_utils was provided complete, not as a placeholder).

### Potentially Obsolete / Dead Code

6. **generator.py** — Intentional stub (workshop exercise), but the solution at generator.py is the real implementation. If a user hasn't filled it in, the file is non-functional.

7. **generate_evidence.py vs generate_evidence.py** — The level_1 version is the same as solutions (not a placeholder), meaning the solutions copy is fully redundant.

8. **README.md** and README.md — Level 2 backend README is empty; the dashboard backend README is comprehensive but references some endpoints inconsistently.

9. **billing-enablement.py** — Lives at the top of level_2/ rather than in a scripts subfolder like levels 3-5, breaking the organizational pattern without adding any different functionality.

### Structural Inconsistencies (Not Obsolete but Notable)

10. **README Level descriptions mismatch** — The top-level README.md table says Levels 3, 4, and 5 all do "Coordinate group rescue / Agent orchestration, consensus protocols" but they actually do very different things (biometric scanner, engine assembly, satellite formation).

11. **Codelab link for Level 1** — Uses `%31` (wrong URL encoding, should be `%201` or just `1`) in the README badge.

12. **Codelab link for Level 2** — Points to `x` (placeholder, not a real URL).

---

## Best Practices Identified in Way Back Home

### 1. `before_agent_callback` — Pre-Hydrate Agent State

**Where**: agent.py

This is one of the strongest patterns in the repo. The callback runs **once** before the root agent starts, fetches all participant data from the backend API, and populates `CallbackContext.state` with everything sub-agents need:

```python
async def setup_participant_context(callback_context: CallbackContext) -> None:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        data = response.json()
    callback_context.state["soil_url"] = evidence_urls.get("soil", "Not available")
    callback_context.state["flora_url"] = evidence_urls.get("flora", "Not available")
    # ... all context set once
```

Then applied to the root agent:
```python
root_agent = Agent(..., before_agent_callback=setup_participant_context)
```

**Benefits**:
- **Reduced token usage**: All context is fetched once and injected via `{key}` state templating in sub-agent instructions (e.g., `{soil_url}`, `{flora_url}`) rather than each agent independently discovering/fetching it
- **Stateless deployment**: No local config files needed — works identically on Cloud Run and locally
- **Single point of failure**: If the data fetch fails, it fails early with clear error messages rather than mid-reasoning
- **Shared state across the agent tree**: The `ParallelAgent`'s 3 specialists all read from the same state without redundant API calls

---

### 2. Docker — Container Image Best Practices

The repo demonstrates a **progression** of Docker maturity across its Dockerfiles:

**Gold standard** — Dockerfile:
- `python:3.11-slim` base (minimal attack surface)
- **Layer caching**: `COPY requirements.txt .` → `RUN pip install` → `COPY app/` (deps cached until requirements change)
- `--no-cache-dir` on pip (no wasted space)
- `--no-install-recommends` + `rm -rf /var/lib/apt/lists/*` (minimal system packages)
- **Non-root user**: `useradd --create-home appuser` + `USER appuser`
- **Health check**: `HEALTHCHECK` directive with startup grace period
- `PYTHONDONTWRITEBYTECODE=1` + `PYTHONUNBUFFERED=1`

**Gold standard (frontend)** — Dockerfile:
- **3-stage multi-stage build**: deps → builder → runner
- `node:20-alpine` for smallest possible images
- Build args (`ARG NEXT_PUBLIC_*`) for environment-specific builds without baking secrets
- Next.js standalone output — only production assets copied to final image
- Non-root `nextjs:1001` user with proper `chown`

**Workshop-level (simpler)** — Dockerfile, Dockerfile:
- Still use slim images + layer caching + apt cleanup
- Level 2 uses `uv` for fast dependency resolution (`uv pip install --system`)
- Missing non-root user and health checks (acceptable for workshop exercises)

---

### 3. Cloud Build — Build → Push → Deploy Pipeline

**Where**: cloudbuild.yaml, cloudbuild.yaml, cloudbuild.yaml

Key patterns:

| Practice | Implementation |
|----------|---------------|
| **Dual tagging** | Every image tagged with both `${BUILD_ID}` (immutable) and `latest` (mutable) for rollback + convenience |
| **Substitution variables** | `_DEPLOY_BACKEND`, `_DEPLOY_FRONTEND` flags allow selective deployment via `--substitutions` |
| **Step dependencies** | `waitFor: ['push-backend']` ensures correct ordering; frontend/backend build in parallel where independent |
| **Artifact Registry** | Uses `${_REGION}way-back-home.` (not legacy `gcr.io`) for the dashboard; Level 2 still uses `gcr.io` |
| **Resource labeling** | Cloud Run services labeled with `app`, `level`, `component`, `dev-tutorial` for cost tracking and filtering |
| **Workspace sharing** | Level 2 saves backend URL to `/workspace/backend_url.txt` for the frontend build step to consume |
| **Machine type** | `E2_HIGHCPU_8` for faster builds; `CLOUD_LOGGING_ONLY` to reduce costs |
| **Scale-to-zero** | All Cloud Run deploys use `--min-instances 0` with appropriate `--max-instances` and `--concurrency` |

---

### 4. Google Managed MCP Server — Authentication Helper

**Where**: star_tools.py

The `get_bigquery_mcp_toolset()` function is a clean helper that authenticates against Google's managed BigQuery MCP endpoint:

```python
def get_bigquery_mcp_toolset():
    credentials, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    credentials.refresh(google.auth.transport.requests.Request())
    
    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "x-goog-user-project": project_id or PROJECT_ID
    }
    
    _bigquery_toolset = MCPToolset(
        connection_params=StreamableHTTPConnectionParams(
            url="https://bigquery.googleapis.com/mcp",
            headers=headers
        )
    )
```

**Key practices**:
- **Singleton pattern** (`_bigquery_toolset` global cache) — avoids re-authentication per call
- **Application Default Credentials** (`google.auth.default`) — works on Cloud Run (metadata server), Cloud Shell (user creds), and local dev (service account key) without code changes
- **Explicit scope** — requests minimum `bigquery` scope
- **Token refresh** — explicitly calls `credentials.refresh()` before extracting the token
- **`x-goog-user-project` header** — required for quota/billing attribution to the correct project

This contrasts with the **custom MCP** pattern in mcp_tools.py which connects to a self-hosted MCP server via `StreamableHTTPConnectionParams(url=f"{MCP_SERVER_URL}/mcp")` — no OAuth needed since it's your own server.

---

### 5. `{key}` State Templating — Zero-cost Context Injection

**Where**: All sub-agents in agents

Instead of each specialist agent calling tools to discover its input, the instructions use direct state references:

```python
geological_analyst = Agent(
    instruction="""...
    Soil sample URL: {soil_url}     # ← Injected from state, no tool call needed
    ...
    Call the analyze_geological tool with the soil sample URL above""",
)
```

**Benefit**: The agent doesn't waste tokens or latency figuring out *what* to analyze — the URL is literally in its instructions. Combined with `before_agent_callback`, this means zero extra API calls for context.

---

### 6. `ToolContext` — State Access Within Tools

**Where**: confirm_tools.py

Tools can read state set by the callback without passing values through LLM reasoning:

```python
def confirm_location(biome: str, tool_context: ToolContext) -> dict:
    participant_id = tool_context.state.get("participant_id", "")
    x = tool_context.state.get("x", 0)
    backend_url = tool_context.state.get("backend_url", "https://api.waybackhome.dev")
```

The `tool_context` parameter is **automatically injected** by ADK — the LLM only needs to provide `biome`, not all the operational parameters. Reduces hallucination risk and simplifies the tool's function signature from the model's perspective.

---

### 7. ParallelAgent — Independent Work Runs Concurrently

**Where**: agent.py

```python
evidence_analysis_crew = ParallelAgent(
    name="EvidenceAnalysisCrew",
    sub_agents=[geological_analyst, botanical_analyst, astronomical_analyst]
)
```

Three independent analyses run simultaneously (~3s) instead of sequentially (~9s). The root agent then applies **2-of-3 consensus** logic to the results — a practical pattern for reliability when using non-deterministic AI outputs.

---

### 8. SequentialAgent Pipeline — Structured Multi-step Processing

**Where**: multimedia_agent.py

A 4-stage pipeline using `output_key` for inter-step data passing:

```
Upload → Extract → Save to Spanner → Summarize
```

Each `LlmAgent` stage has `output_key="upload_result"`, `output_key="extraction_result"`, etc., and subsequent stages reference `{upload_result}` in their instructions. Guarantees correct ordering and clean data flow.

---

### 9. Config Resolution Pattern — Local + Cloud Portability

**Where**: config_utils.py

Priority chain:
1. **Environment variables** (`PARTICIPANT_ID`, `BACKEND_URL`) → for Cloud Run
2. **Local config.json** (searched upward from `__file__`) → for local dev
3. **Cached result** → avoids repeated file reads or API calls

This ensures the same codebase works in Cloud Shell, local IDE, and Cloud Run without any code changes.

---

### 10. Infrastructure-as-Script

**Where**: setup-infrastructure.sh

A single idempotent script that:
- Enables all GCP APIs
- Creates IAM role bindings for Cloud Build, Compute, and Firebase service accounts
- Creates Artifact Registry repo (with existence check)
- Creates Firestore database (with existence check)
- Configures Firebase Storage bucket ACLs
- Creates composite Firestore indexes

Every operation checks for pre-existence before creating, making it safe to re-run.

---

### Summary Table

| Pattern | Where | Key Benefit |
|---------|-------|-------------|
| `before_agent_callback` | Level 1 root agent | Single fetch, shared state, reduced tokens |
| `{key}` state templating | All Level 1 sub-agents | Zero-cost context injection into instructions |
| `ToolContext` state access | `confirm_tools.py` | Tools read state without LLM intermediation |
| Docker layer caching | All Dockerfiles | Fast rebuilds, requirements cached separately |
| Multi-stage Docker builds | Dashboard frontend, solutions L3/L4 | Tiny production images, build deps excluded |
| Non-root user | Dashboard backend/frontend | Security hardening |
| Cloud Build dual tagging | cloudbuild.yaml | `BUILD_ID` for rollback + `latest` for convenience |
| Selective deploy flags | `_DEPLOY_BACKEND`/`_DEPLOY_FRONTEND` | Deploy only what changed |
| Google Managed MCP auth | `star_tools.py` | ADC + singleton + explicit scope + quota header |
| Custom MCP singleton | `mcp_tools.py` | Single connection reused across calls |
| `ParallelAgent` | Level 1 evidence crew | 3x faster than sequential, plus consensus |
| `SequentialAgent` + `output_key` | Level 2 multimedia pipeline | Structured multi-step with data handoff |
| Config resolution chain | `config_utils.py` | Same code works local + Cloud Run |
| Idempotent infra scripts | `setup-infrastructure.sh` | Safe to re-run, checks before creating |

---

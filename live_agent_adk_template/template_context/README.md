# AI3D memAdmin

**Voice-driven 3D semantic memory administration for live AI agents.**

> *Gemini Live Agent Challenge — Live Agents Category*

AI3D memAdmin gives operators a real-time 3D atlas of an AI agent's semantic memory. Inspect, diagnose, and directly edit memories — with your voice. The embedded ADK agent can read its own memory graph, detect fixation, and prescribe fixes with clickable citations.

![Architecture Diagram](docs/architecture-diagram.png)
<!-- Upload this same image to the DevPost Image Gallery / File Upload -->

---

## Architecture

```
BROWSER (React 18 + React Three Fiber)
├── 3D ATLAS VIEWPORT (Three.js 0.169, WebGL, Bloom post-processing)
│   ├── SemanticNodes (sphere geometry + labels)
│   ├── SimilarityEdges (core + glow tubes, cosine >= 0.70)
│   ├── ClusterHulls (convex hull volumes)
│   ├── TrajectoryPaths (dashed, pattern-colored)
│   └── StabilizingIndicator (pulse + torus ring)
│
├── HUD PANELS
│   ├── StatusHUD (nodes, landmarks, connection)
│   ├── NodeInspector (relabel/annotate/pin/hide/delete)
│   ├── TrajectoryHUD (pattern + drift + segments)
│   ├── EventInput (inject/search + file upload)
│   ├── AgentChat (ADK agent + clickable citations)
│   ├── TimelineScrubber (play/scrub/speed)
│   ├── MathTutorial (6 KaTeX algorithm sections)
│   ├── VoiceMic (5-state Live API toggle)
│   └── SubtitleBar (live transcription)
│
├── VOICE PIPELINE (Gemini Live API)
│   ├── Mic → AudioWorklet (PCMProcessor, 16kHz, TypedArray ring-buffer resampler)
│   │   └── → PCM Int16 chunks (1600 samples / 100 ms) → WebSocket binary frames
│   ├── → Gemini Live API (client-direct WebSocket)
│   │   ├── Audio output (24kHz) → Speaker
│   │   ├── Tool calls → REST backend
│   │   └── Transcriptions → SubtitleBar
│   └── WebSocket trajectory_alert → proactive voice narration
│
└── STATE: Zustand 5.0 reactive store
            │
            ▼
     FASTAPI BACKEND (Python 3.11+)
     ├── Semantic Pipeline
     │   ├── Embed (Gemini Embedding 2, up to 3072D)
     │   ├── Project (Landmark Atlas PCA)
     │   ├── Cluster (k-means, auto-k)
     │   ├── Store (Vertex AI Vector Search / Qdrant)
     │   ├── Track (Trajectory 5-point window, 4 patterns)
     │   └── Broadcast (WebSocket hub)
     │
     ├── ADK Agent (Gemini 2.5 Flash)
     │   └── 7 tools: search_memory, get_trajectory_summary,
     │       get_atlas_stats, edit_node, ingest_text,
     │       search_by_annotation, ingest_image
     │
     └── REST + WebSocket Endpoints
         ├── POST /api/events (+ batch/upload)
         ├── GET  /api/nodes/search
         ├── POST /api/nodes/edit
         ├── GET  /api/trajectories
         ├── POST /api/agent/chat
         ├── POST /api/voice/token
         ├── POST /api/demo/seed
         └── WS   /ws
```

---

## Key Features

| Category | Features |
|----------|----------|
| **Visualization** | 3D semantic atlas, cluster hulls, similarity edges, trajectory paths, stabilizing indicator, bloom post-processing |
| **Memory Editing** | Relabel, annotate (behavioral keywords), pin, hide, delete — all broadcast in real time |
| **Trajectory Detection** | 4 patterns (EXPLORING, STABILIZING, REVISITING, MODALITY SHIFT) with proactive alerts |
| **Voice Control** | Gemini Live API — search, inject, diagnose by voice with live transcription |
| **Agent Self-Diagnosis** | ADK agent reads its own trajectory, searches its own memory, prescribes fixes with clickable `[[node:UUID|label]]` citations |
| **Timeline Replay** | Event-time scrubbing — rewind and replay any incident |
| **Math Transparency** | Full KaTeX documentation of all algorithms (Landmark PCA, cosine similarity, trajectory detection, etc.) |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for Qdrant local vector store)
- A Google AI API key (`GOOGLE_API_KEY`)

### 1. Clone and Setup

```bash
git clone https://github.com/YOUR_ORG/ai3d-memadmin.git
cd ai3d-memadmin

# Copy env and add your API key
cp .env.example .env
# Edit .env → set GOOGLE_API_KEY

# Create Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Install frontend deps
cd frontend && npm install && cd ..
```

### 2. Start Qdrant (local vector store)

```bash
docker run -d --name qdrant-memadmin -p 6333:6333 qdrant/qdrant:latest
```

### 3. Start Backend

```bash
uvicorn server:app --host 0.0.0.0 --port 8080 --reload
```

### 4. Start Frontend

```bash
cd frontend
npm run dev
```

Open **http://localhost:5173**

### One-Command Dev

```bash
bash scripts/dev.sh
```

This starts Qdrant, backend, and frontend in one terminal.

---

## Reproducible Testing

Follow these steps to verify all core features end-to-end.

### Step 1: Seed the Atlas

Click **"Load Demo"** in the StatusHUD (top-left), or run:

```bash
curl -X POST http://localhost:8080/api/demo/seed
```

This injects 25 diverse memories (Roman history, jazz, quantum physics, sourdough, etc.) and establishes an EXPLORING trajectory baseline.

### Step 2: Verify 3D Atlas

- [ ] 25 nodes appear as colored spheres in the 3D viewport
- [ ] Clusters form visually (science, music, food, etc.)
- [ ] Similarity edges connect semantically related nodes
- [ ] Orbiting, zooming, and panning work (mouse drag/scroll/right-drag)

### Step 3: Test Memory Injection

Switch EventInput to **Inject** mode. Type:

```
Using transformer attention heads to model protein folding
```

- [ ] New node materializes with spring animation from previous trajectory point
- [ ] Node lands between ML and science clusters
- [ ] Similarity edges connect to related nodes

### Step 4: Test Semantic Search

Switch EventInput to **Search** mode. Type: `music theory`

- [ ] Results appear with similarity percentages
- [ ] Clicking a result focuses the camera and opens the NodeInspector

### Step 5: Test Memory Editing

In the NodeInspector:

- [ ] **Relabel** — change the node's label text
- [ ] **Annotate** — add `review: fixation risk` → verify it appears in the inspector
- [ ] **Pin/Unpin** — toggle pin state
- [ ] **Delete** — remove a node (hard delete)

### Step 6: Test Trajectory Detection

Rapidly inject 5 ML-focused memories:

```
Gradient descent optimization for neural networks
Learning rate scheduling and warm-up strategies
Batch normalization and training stability
Backpropagation through computational graphs
Dropout regularization and overfitting prevention
```

- [ ] Trajectory HUD shifts from EXPLORING → STABILIZING
- [ ] Convergence sphere appears around the fixation cluster

### Step 7: Test Agent Self-Diagnosis

Open the **Agent Chat** panel. Type:

```
Trajectory went STABILIZING. What's happening?
```

- [ ] Agent calls `get_trajectory_summary` + `search_memory`
- [ ] Response includes clickable `[[node:UUID|label]]` citations
- [ ] Clicking a citation zooms the camera to that node

### Step 8: Test Voice (requires microphone + speakers)

Click the **mic button** (bottom-right). Wait for green "Listening" state.

- [ ] Say: *"Search for anything about music"* → agent responds with audio + subtitles
- [ ] Say: *"Ingest a new memory: Comparing Renaissance painting with modern generative art"* → new node appears
- [ ] Trajectory alert fires → agent speaks proactively without being asked

Click mic to stop voice session.

### Step 9: Test Timeline Replay

Grab the **timeline scrubber**. Drag all the way left (atlas empties). Slowly drag right.

- [ ] Nodes appear one by one in event-time order
- [ ] Fixation pattern visible in slow motion
- [ ] Fix injection restores EXPLORING

### Step 10: Test Math Tutorial

Click the **Math Tutorial** panel (bottom-right expandable).

- [ ] 6 KaTeX sections render with proper notation
- [ ] Toggle **Researcher Mode** → live stats appear

---

## Cloud Run Deployment

### Automated Deployment Script

> **[`infra/cloudrun/deploy.sh`](infra/cloudrun/deploy.sh)** — Single-command Cloud Run deployment with Cloud Build.

```bash
# Set your Google AI Studio API key (for voice/Live API)
export GOOGLE_API_KEY="your-key-here"

# Deploy
bash infra/cloudrun/deploy.sh YOUR_PROJECT_ID us-central1
```

The script:
1. Builds a multi-stage Docker image (Node.js frontend build → Python runtime)
2. Pushes to Artifact Registry via Cloud Build
3. Deploys to Cloud Run with Vertex AI, session affinity, and auto-scaling (1–5 instances)
4. Passes `GOOGLE_API_KEY` for voice features if set in environment

### Prerequisites

- `gcloud` CLI authenticated (`gcloud auth login`)
- GCP project with these APIs enabled:
  - Artifact Registry
  - Cloud Run
  - Vertex AI
  - Gemini API
- `GOOGLE_API_KEY` from [AI Studio](https://aistudio.google.com/) for voice features

### Cloud Run Configuration

| Setting | Value |
|---------|-------|
| Memory | 1 GiB |
| CPU | 2 |
| Min instances | 1 |
| Max instances | 5 |
| Session affinity | Enabled |
| Vector store | Vertex AI Vector Search |
| Embedding model | Gemini Embedding 2 |

---

## Project Structure

```
ai3d-memadmin/
├── adk_app/                    # ADK agent runtime
│   ├── agents/memadmin.py      # Root agent definition
│   ├── tools/memory_tools.py   # 7 custom ADK tools
│   ├── callbacks/              # Semantic telemetry hooks
│   ├── runtime/pipeline.py     # Semantic event pipeline
│   └── agent.py                # ADK entry point
├── backend/
│   ├── config.py               # Environment-based config
│   ├── models.py               # Shared Pydantic models
│   ├── embeddings/service.py   # Gemini Embedding 2 client
│   ├── vectorstore/            # Pluggable vector storage
│   │   ├── base.py             # Abstract interface
│   │   ├── qdrant_store.py     # Qdrant implementation
│   │   ├── vertex_store.py     # Vertex AI Vector Search
│   │   └── factory.py          # Backend factory
│   ├── atlas/engine.py         # Landmark-based 3D atlas
│   ├── trajectories/tracker.py # Trajectory pattern detection
│   └── websocket/hub.py        # WebSocket broadcast hub
├── frontend/
│   └── src/
│       ├── scene/              # Three.js/R3F 3D components
│       ├── components/         # HUD panels (9 components)
│       ├── state/store.ts      # Zustand state management
│       └── streaming/ws.ts     # WebSocket client
├── infra/
│   ├── cloudrun/deploy.sh      # Automated Cloud Run deployment
│   └── env/cloudrun.env        # Cloud Run env template
├── scripts/
│   ├── dev.sh                  # One-command local dev
│   └── seed.sh                 # Sample data seeder
├── server.py                   # FastAPI application
├── Dockerfile                  # Multi-stage container build
└── pyproject.toml
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/events` | Ingest a semantic event (text or image) |
| POST | `/api/events/batch` | Batch ingest events |
| POST | `/api/events/upload` | Upload file for ingestion |
| GET | `/api/atlas/snapshot` | Full atlas state (all nodes, edges, clusters) |
| POST | `/api/nodes/edit` | Edit a memory node (relabel/annotate/pin/hide/delete) |
| GET | `/api/nodes/search?query=...&top_k=8` | Semantic similarity search |
| GET | `/api/trajectories` | Trajectory data and pattern history |
| GET | `/api/stats` | System statistics |
| POST | `/api/agent/chat` | Chat with ADK agent |
| POST | `/api/voice/token` | Ephemeral token for Gemini Live API |
| POST | `/api/demo/seed` | Inject 25 demo memories (idempotent) |
| WS | `/ws` | Real-time atlas updates |

---

## Models and APIs Used

| Model | Purpose |
|-------|---------|
| **Gemini 2.5 Flash** | ADK agent — conversational tool-calling, self-diagnosis |
| **Gemini 2.5 Flash Native Audio Preview** | Live API — sub-second bidirectional voice |
| **Gemini Embedding 2** | 3,072-dimensional multimodal embeddings |
| **Ephemeral Tokens** | v1alpha auth tokens for secure client-direct voice |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| 3D Rendering | Three.js 0.169 + React Three Fiber 8.17 + Bloom post-processing |
| UI Framework | React 18.3 + Zustand 5.0 |
| Backend | FastAPI + Python 3.11+ |
| Agent Framework | Google ADK >= 1.0 |
| Voice | Gemini Live API (client-direct WebSocket) |
| Vector Storage | Vertex AI Vector Search (cloud) / Qdrant (local) |
| Math Rendering | KaTeX 0.16 |
| Deployment | Cloud Run, Cloud Build, Artifact Registry |

---

## License

MIT

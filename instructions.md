# SENTINEL — How to Get the App Up and Running

This guide covers local development, applying changes, and deploying to Google Cloud.

---

## 1. Prerequisites

| Tool | Install |
|------|---------|
| **Python 3.11+** | [python.org](https://www.python.org/downloads/) |
| **ffmpeg** | `sudo apt install ffmpeg` (Linux) · `brew install ffmpeg` (Mac) · `winget install ffmpeg` (Windows) |
| **Google Cloud SDK** | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) (only needed for GCP deployment) |
| **Docker** *(optional)* | [docker.com](https://docs.docker.com/get-docker/) (only if you want to run in a container locally) |

---

## 2. Initial Setup (One-Time)

```bash
# Clone the repo
git clone https://github.com/lohjo/jwj2026.git
cd jwj2026

# Create a virtual environment
python -m venv .venv

# Activate it
# Linux / Mac:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Configure environment variables

```bash
# Copy the example and fill in your keys
cp .env.example .env
```

Open `.env` in your editor and set **at minimum** these three required values:

```
TELEGRAM_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_sealion_api_key_from_aisingapore
GEMINI_API_KEY=your_gemini_api_key
```

> **Note:** `OPENAI_API_KEY` is the API key for AI Singapore's SEA-LION
> service (accessed via an OpenAI-compatible endpoint), **not** an OpenAI key.

All other variables have sensible defaults and are optional.

---

## 3. Running Locally (localhost)

SENTINEL has **two entry points** — choose based on what you need:

### Option A: Telegram Bot (primary)

This starts the Telegram bot with long-polling. It also spins up a lightweight
health-check HTTP server on port 8080 (for Cloud Run compatibility).

```bash
python telegram_bot.py
```

- The bot will respond to messages in Telegram.
- `http://localhost:8080` serves only a health-check endpoint (any `GET`
  request returns `200 OK`) — it is **not** a full web UI.

### Option B: FastAPI Detection API

This starts the REST API with endpoints for text, image, video, and
misinformation detection.

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

- Open `http://localhost:8000` — you should see
  `{"message": "Fake Media Detector API running"}`.
- Interactive API docs are at `http://localhost:8000/docs`.
- The `--reload` flag watches for file changes and **automatically restarts**
  the server when you save a file.

---

## 4. How Do I Update localhost to Show My Changes?

### If you are running with `uvicorn --reload` (Option B above)

**You don't need to do anything.** Save your file and uvicorn will detect the
change and restart the server automatically. Refresh your browser to see the
updated response.

### If you are running `python telegram_bot.py` (Option A)

Stop the bot (`Ctrl+C`), then start it again:

```bash
# Stop with Ctrl+C, then:
python telegram_bot.py
```

### If you are running with Docker

Rebuild and restart the container:

```bash
docker build -t sentinel .
docker run --env-file .env -p 8080:8080 sentinel
```

> **Note:** There is no `docker-compose.yml` in this repository, so
> `docker compose up --build` will **not work** unless you create one yourself.
> Use the `docker build` + `docker run` commands above instead.

---

## 5. Running with Docker (Optional)

If you prefer containerised development:

```bash
# Build the image
docker build -t sentinel .

# Run the Telegram bot
docker run --env-file .env -p 8080:8080 sentinel

# Or run the FastAPI server instead (override the CMD)
docker run --env-file .env -p 8000:8000 sentinel \
  uvicorn app:app --host 0.0.0.0 --port 8000
```

To apply code changes when using Docker, **rebuild the image** each time:

```bash
docker build -t sentinel .
docker run --env-file .env -p 8080:8080 sentinel
```

---

## 6. Deploying to GCP Cloud Run

### First-time setup

```bash
# Authenticate
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID
gcloud config set run/region asia-southeast1

# Enable required APIs
gcloud services enable 
 run.googleapis.com
 cloudbuild.googleapis.com
 artifactregistry.googleapis.com
 aiplatform.googleapis.com
  --project jwjbot
```

### Deploy (build + push + deploy in one command)

```bash
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY" \
  --set-env-vars "OPENAI_API_BASE=https://api.sea-lion.ai/v1" \
  --set-env-vars "GROQ_API_KEY=$GROQ_API_KEY" \
  --set-env-vars "DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY" \
  --set-env-vars "ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY" \
  --set-env-vars "CLICKHOUSE_HOST=$CLICKHOUSE_HOST" \
  --set-env-vars "CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=FALSE"
```

This command:
1. Uploads your source code (respecting `.gcloudignore`).
2. Builds the Docker image in the cloud using Cloud Build.
3. Deploys the image to Cloud Run.
4. Prints the live service URL when finished.

### Verify the deployment is live

```bash
# Get the service URL
gcloud run services describe sentinel \
  --region asia-southeast1 \
  --format="value(status.url)"

# Check recent logs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" \
  --limit 20 \
  --format="table(timestamp, textPayload)"
```

Visit the URL printed by the first command — it should respond to confirm the
service is running.

### Re-deploying after changes

Every time you make code changes and want the live GCP URL to reflect them,
run the **same `gcloud run deploy` command** again (with all `--set-env-vars`
flags). It will rebuild and redeploy automatically.

```bash
# Same command as the initial deploy — re-run it each time you change code
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN" \
  --set-env-vars "GEMINI_API_KEY=$GEMINI_API_KEY" \
  --set-env-vars "OPENAI_API_KEY=$OPENAI_API_KEY" \
  --set-env-vars "OPENAI_API_BASE=https://api.sea-lion.ai/v1" \
  --set-env-vars "GROQ_API_KEY=$GROQ_API_KEY" \
  --set-env-vars "DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY" \
  --set-env-vars "ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY" \
  --set-env-vars "CLICKHOUSE_HOST=$CLICKHOUSE_HOST" \
  --set-env-vars "CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD" \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=FALSE"
```

> **Tip:** You do not need Docker installed locally for GCP deployment —
> Cloud Build handles the Docker build in the cloud.

### Automated deployment (CI/CD)

The repository includes a `cloudbuild.yaml` that automates the build-push-deploy
pipeline. To use it:

```bash
gcloud builds submit --config cloudbuild.yaml .
```

---

## 7. Quick Reference

| Task | Command |
|------|---------|
| Run Telegram bot locally | `python telegram_bot.py` |
| Run FastAPI server locally | `uvicorn app:app --host 0.0.0.0 --port 8000 --reload` |
| Run tests | `python -m pytest tests/ -v` |
| Build Docker image | `docker build -t sentinel .` |
| Run Docker container | `docker run --env-file .env -p 8080:8080 sentinel` |
| Deploy to GCP | `gcloud run deploy sentinel --source . --region asia-southeast1 ...` |
| Check GCP service URL | `gcloud run services describe sentinel --region asia-southeast1 --format="value(status.url)"` |
| View GCP logs | `gcloud logging read "resource.labels.service_name=sentinel" --limit 20` |
| Verify hackathon compliance | `python verify_hackathon.py` |

---

## 8. Troubleshooting

### "Missing required env var" error on startup

Make sure your `.env` file exists and contains at least `TELEGRAM_TOKEN`,
`OPENAI_API_KEY`, and `GEMINI_API_KEY`. See `.env.example` for the full list.

### `docker compose up --build` doesn't work

This project does **not** include a `docker-compose.yml` file. Use
`docker build` and `docker run` directly instead (see Section 5).

### Changes not showing on localhost

- **uvicorn with `--reload`:** Changes are picked up automatically — just
  refresh your browser.
- **`python telegram_bot.py`:** Stop and restart the script.
- **Docker:** You must rebuild the image (`docker build -t sentinel .`) and
  restart the container.

### GCP deployment URL not updating

Run `gcloud run deploy sentinel --source . ...` again. Each deploy creates a
new revision. The URL stays the same but serves the latest code.

### ffmpeg not found

Install ffmpeg for your OS (see Prerequisites). It is required for audio
processing. The Docker image installs it automatically.

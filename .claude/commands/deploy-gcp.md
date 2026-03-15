# Deploy SENTINEL to Google Cloud Run

Execute a full GCP deployment for SENTINEL. Work through every step in order.
This command satisfies the hackathon's mandatory "hosted on Google Cloud" requirement.

## Pre-flight checks

Before writing any code, verify the following. Stop and surface errors — do not proceed if any fail.

```bash
# 1. Confirm gcloud is authenticated
gcloud auth list

# 2. Confirm active project is set
gcloud config get-value project

# 3. Confirm region is set
gcloud config get-value run/region

# 4. Confirm .env is NOT committed
git status .env
```

If any of the above fail, fix them before continuing.

## Step 1 — Create Dockerfile (if not present)

Check if `Dockerfile` exists. If not, create it:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080

CMD ["python", "telegram_bot.py"]
```

## Step 2 — Create .gcloudignore (if not present)

```
.env
.venv/
__pycache__/
*.pyc
downloads/
uploads/
frames/
research/raw/
.git/
tests/
.claude/
```

## Step 3 — Enable required GCP APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com
```

## Step 4 — Load env vars from .env and deploy

Read all required values from `.env`, then run:

```bash
gcloud run deploy sentinel \
  --source . \
  --region asia-southeast1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-env-vars "TELEGRAM_TOKEN=$TELEGRAM_TOKEN,GEMINI_API_KEY=$GEMINI_API_KEY,OPENAI_API_KEY=$OPENAI_API_KEY,OPENAI_API_BASE=https://api.sea-lion.ai/v1,GROQ_API_KEY=$GROQ_API_KEY,DEEPGRAM_API_KEY=$DEEPGRAM_API_KEY,ELEVENLABS_API_KEY=$ELEVENLABS_API_KEY,CLICKHOUSE_HOST=$CLICKHOUSE_HOST,CLICKHOUSE_PASSWORD=$CLICKHOUSE_PASSWORD,GOOGLE_GENAI_USE_VERTEXAI=FALSE,GEMINI_LIVE_MODEL=gemini-2.0-flash-live-001"
```

## Step 5 — Verify deployment

```bash
# Get the live URL
gcloud run services describe sentinel \
  --region asia-southeast1 \
  --format="value(status.url)"

# Tail logs to confirm bot started
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" \
  --limit 20 --format="table(timestamp,textPayload)"
```

Expected log line: `Starting Telegram bot polling...`

## Step 6 — Create cloudbuild.yaml for automated deploys (hackathon bonus points)

If `cloudbuild.yaml` does not exist, create it:

```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/sentinel', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/sentinel']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - sentinel
      - --image=gcr.io/$PROJECT_ID/sentinel
      - --region=asia-southeast1
      - --platform=managed
      - --allow-unauthenticated
      - --memory=2Gi
      - --cpu=2
images:
  - 'gcr.io/$PROJECT_ID/sentinel'
```

## Step 7 — Record deployment proof

For the hackathon submission you need one of:
- A screen recording showing the Cloud Run console with SENTINEL running
- A link to `cloudbuild.yaml` in the repo demonstrating GCP API usage

Output the Cloud Run service URL as the final line of this command.

## Arguments

$ARGUMENTS

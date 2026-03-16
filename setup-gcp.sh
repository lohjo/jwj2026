#!/usr/bin/env bash
# setup-gcp.sh — Idempotent GCP infrastructure bootstrap for SENTINEL.
#
# Enables required APIs and creates the Artifact Registry repository.
# Safe to re-run — all operations are idempotent.
#
# Usage:
#   gcloud auth login
#   gcloud config set project YOUR_PROJECT_ID
#   bash setup-gcp.sh

set -euo pipefail

REGION="${GCP_REGION:-asia-southeast1}"
AR_REPO="${AR_REPO_NAME:-sentinel}"
SERVICE="${CLOUD_RUN_SERVICE:-sentinel}"

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
if [[ -z "$PROJECT_ID" ]]; then
  echo "ERROR: No GCP project set. Run: gcloud config set project YOUR_PROJECT_ID"
  exit 1
fi

echo "==> Project:  $PROJECT_ID"
echo "==> Region:   $REGION"
echo "==> AR Repo:  $AR_REPO"
echo "==> Service:  $SERVICE"
echo ""

# ── 1. Enable required APIs ──────────────────────────────────────────────────
echo "==> Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  --quiet

echo "    APIs enabled."

# ── 2. Create Artifact Registry Docker repository ────────────────────────────
echo "==> Creating Artifact Registry repository '$AR_REPO' (if needed)..."
if gcloud artifacts repositories describe "$AR_REPO" \
    --location="$REGION" --format="value(name)" 2>/dev/null; then
  echo "    Repository already exists — skipping."
else
  gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="SENTINEL container images" \
    --quiet
  echo "    Repository created."
fi

# ── 3. Summary ───────────────────────────────────────────────────────────────
echo ""
echo "==> GCP infrastructure ready."
echo "    Artifact Registry: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}"
echo ""
echo "Next steps:"
echo "  1. Set environment variables for Cloud Run (see CLAUDE.md)"
echo "  2. Deploy: gcloud run deploy $SERVICE --source . --region $REGION"
echo "  3. Or use Cloud Build: gcloud builds submit --config cloudbuild.yaml"

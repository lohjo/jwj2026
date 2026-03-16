# NOTE: This script is a standalone hackathon/verification tool and is an intentional
# exception to the project convention that only config.py may call os.getenv().
# If this script is promoted to production use, refactor it to import configuration
# values from config.py instead of calling os.getenv() directly.
"""
verify_gcp.py — Demonstrates Google Cloud service usage for hackathon proof.

When running on Cloud Run, K_SERVICE and K_REVISION are injected automatically
by GCP.  Their presence in logs proves the code ran on Cloud Run.

Link this file in the DevPost submission as GCP hosting evidence.

Run:
    python verify_gcp.py
"""

import os

# Cloud Run metadata — only populated when running ON Cloud Run
CLOUD_RUN_SERVICE = os.getenv("K_SERVICE", "not-on-cloud-run")
CLOUD_RUN_REVISION = os.getenv("K_REVISION", "unknown")

# Vertex AI endpoint (Google Cloud service)
_location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-southeast1")
_project = os.getenv("GOOGLE_CLOUD_PROJECT", "<not-set>")
VERTEX_ENDPOINT = (
    f"https://{_location}-aiplatform.googleapis.com/v1"
    f"/projects/{_project}/locations/{_location}"
    f"/publishers/google/models/gemini-2.0-flash-live-001"
)

if __name__ == "__main__":
    print(f"Service:            {CLOUD_RUN_SERVICE}")
    print(f"Revision:           {CLOUD_RUN_REVISION}")
    print(f"Vertex AI endpoint: {VERTEX_ENDPOINT}")

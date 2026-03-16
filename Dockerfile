FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps: ffmpeg (pydub audio conversion) + OpenCV headless runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Create runtime user early so source copy can set ownership without a later chown pass.
RUN useradd -m appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY --chown=appuser:appuser . .
USER appuser

# Cloud Run injects PORT; serve the web UI via uvicorn (FastAPI)
ENV PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]

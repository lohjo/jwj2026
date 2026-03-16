FROM python:3.11-slim

WORKDIR /app

# System deps: ffmpeg (pydub audio conversion) + OpenCV headless runtime
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for security
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Cloud Run injects PORT; uvicorn serves the web UI + API
ENV PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

# Start the web UI/API via uvicorn.  The Telegram bot can be started
# separately or integrated via a startup event in app.py.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]

FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: ffmpeg (pydub audio conversion) + OpenCV headless runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
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

# Cloud Run injects PORT; telegram_bot.py uses polling, not HTTP
ENV PORT=8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys; sys.exit(0)"]

CMD ["python", "telegram_bot.py"]

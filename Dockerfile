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

# Cloud Run injects PORT; telegram_bot.py uses polling, not HTTP
ENV PORT=8080

CMD ["python", "telegram_bot.py"]

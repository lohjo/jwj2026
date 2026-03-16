# SENTINEL Web Interface — User Instructions

## Prerequisites

- **Docker Desktop** installed and running ([download](https://www.docker.com/products/docker-desktop/))
- A `.env` file in the project root with your API keys (copy from `.env.example`):
  ```
  cp .env.example .env
  ```
  At minimum, fill in these **required** keys:
  - `TELEGRAM_TOKEN`
  - `OPENAI_API_KEY` (SEA-LION)
  - `GEMINI_API_KEY`

---

## Quick Start

### 1. Build and run with Docker Compose

```bash
docker compose up --build
```

This builds the Docker image and starts the SENTINEL web server on **port 8080**.

### 2. Open the web interface

Navigate to:

```
http://localhost:8080
```

### 3. Stop the server

Press `Ctrl+C` in the terminal, or run:

```bash
docker compose down
```

---

## Running without Docker (local Python)

If you prefer to run directly:

```bash
# Activate virtual environment
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the web server
python -m uvicorn app:app --host 0.0.0.0 --port 8080
```

Then open `http://localhost:8080`.

---

## Using the Web Interface

The SENTINEL web interface has **four tabs**:

### 📝 Text Detection

1. Click the **Text** tab (selected by default).
2. Paste or type the text you want to analyse into the text area.
3. Click **Analyse Content**.
4. The pipeline runs three steps in real time (streamed via SSE):
   - **GUARD** — safety classification (SEA-LION GUARD model)
   - **Misinformation** — checks for AI-assisted misinformation
   - **Insights** — generates an explanation with Gemini (Groq fallback)
5. Results appear with a verdict card: ✅ Safe, 🚨 Unsafe, or ⚠️ Unknown.

### 🎙 Voice (Live API)

1. Click the **Voice (Live API)** tab.
2. Click the **microphone button** to start recording.
3. Speak your message.
4. Click the button again to stop recording.
5. Your audio is sent to the **Gemini Live API** which returns a spoken verdict.
6. The audio response plays automatically in the browser.

> **Note:** Your browser will ask for microphone permission the first time.

### 🖼 Image Detection

1. Click the **Image** tab.
2. Drag and drop an image file, or click to browse and select one.
3. Click **Analyse Image**.
4. SENTINEL extracts text via OCR and checks for AI-generation artifacts / manipulation.

### 🎬 Video Detection

1. Click the **Video** tab.
2. Upload a video file (MP4, WebM, etc.).
3. Click **Analyse Video**.
4. SENTINEL samples frames and audio, running them through the detection pipeline.

---

## API Endpoints

If you want to test directly via `curl` or a REST client:

| Method | Endpoint                  | Description                                  |
|--------|---------------------------|----------------------------------------------|
| GET    | `/`                       | Web interface                                |
| GET    | `/health`                 | Health check                                 |
| POST   | `/detect-text`            | GUARD text detection (`text` form field)     |
| POST   | `/detect-misinformation`  | Misinformation detection (`text`, `context`) |
| POST   | `/detect-image`           | Image OCR + analysis (file upload)           |
| POST   | `/detect-image-manipulation` | Deepfake / manipulation detection (file upload) |
| POST   | `/ocr`                    | Extract text from image (file upload)        |
| POST   | `/detect-video`           | Video analysis (file upload)                 |
| POST   | `/analyse`                | Full pipeline — text (form field)            |
| POST   | `/analyse-stream`         | Full pipeline with SSE streaming (JSON body) |
| POST   | `/analyse-audio`          | Gemini Live API audio exchange (file upload) |
| WS     | `/ws/live-audio`          | WebSocket for real-time audio                |

### Example: analyse text via curl

```bash
curl -X POST http://localhost:8080/detect-text -F "text=This is a test message to check for AI content"
```

### Example: full pipeline with streaming

```bash
curl -X POST http://localhost:8080/analyse-stream \
  -H "Content-Type: application/json" \
  -d '{"text": "Breaking news: scientists discover water on Mars"}'
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `docker compose` not recognised | Ensure Docker Desktop is running. Use `docker-compose` (hyphenated) on older versions. |
| Port 8080 already in use | Change the port mapping in `docker-compose.yml`: `"9090:8080"`, then visit `http://localhost:9090`. |
| API errors / empty results | Check that your `.env` file has valid API keys. View logs with `docker compose logs -f`. |
| Microphone not working | Ensure you allowed microphone access in your browser. HTTPS is required for mic access in some browsers — for local testing, `localhost` is exempt. |
| Image/video upload fails | Confirm `ffmpeg` and OpenCV dependencies are installed (handled automatically by Docker). |

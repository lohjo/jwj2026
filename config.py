
import os

# Gemini configuration: prefer environment variables
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Default model name for Gemini; can be overridden by env `MODEL_NAME`
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-flash")

def extract_frames(video_path):
    try:
        import cv2
    except Exception as e:
        raise RuntimeError("opencv (cv2) is required for extract_frames: " + str(e))

    cap = cv2.VideoCapture(video_path)
    frames = []
    count = 0

    os.makedirs("frames", exist_ok=True)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if count % 30 == 0:
            path = f"frames/frame_{count}.jpg"
            cv2.imwrite(path, frame)
            frames.append(path)

        count += 1

        if count > 150:
            break

    cap.release()
    return frames

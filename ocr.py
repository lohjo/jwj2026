from utils.frame_extractor import extract_frames
from detectors.text_detector import detect_fake_image
from typing import Dict, Any, Union

# Post-OCR translation hook
# Caller (agent.py) is responsible for calling detect_language() and
# translate_to_english() on this output before passing to run_guard_detection.
# This function returns raw extracted text only - language-agnostic.

def detect_fake_video(path: str, label_language: bool = False) -> Union[str, Dict[str, Any]]:
    """
    Detect AI-generated video by sampling frames and analysing them.
    
    Args:
        path: Path to the video file.
        label_language: If True, return a dict with text and detected language.
                       If False (default), return raw extracted text string.
    
    Returns:
        If label_language=False: raw extracted text string.
        If label_language=True: {"text": "extracted text here", "detected_lang": "en"}
        Otherwise returns detection results: {"frames_checked": int, "suspicious_frames": int, "fake_probability": float}
    """
    frames = extract_frames(path)

    results = []
    suspicious = 0

    for frame in frames:
        result = detect_fake_image(frame)
        results.append(result)

        if result["edge_score"] > 25:
            suspicious += 1

    probability = suspicious / len(results) if results else 0

    return {
        "frames_checked": len(results),
        "suspicious_frames": suspicious,
        "fake_probability": probability
    }

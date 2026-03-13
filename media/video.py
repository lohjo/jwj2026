"""
media/video.py — OpenCV frame sampling + ffmpeg audio extraction.
"""

import asyncio
import logging
import os
import tempfile

from media.image import analyse_image_with_gemini
from media.audio import transcribe_audio

logger = logging.getLogger(__name__)


def extract_frames(video_path: str, max_frames: int = 5) -> list[str]:
    """
    Extract frames from a video at regular intervals.

    Args:
        video_path: Path to the video file.
        max_frames: Maximum number of frames to extract.

    Returns:
        List of file paths to extracted frame images.
    """
    try:
        import cv2
    except ImportError:
        logger.warning("[Video] OpenCV not available")
        return []

    cap = cv2.VideoCapture(video_path)
    frames = []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        cap.release()
        return []

    interval = max(1, total_frames // max_frames)
    os.makedirs("frames", exist_ok=True)
    count = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if count % interval == 0 and len(frames) < max_frames:
            path = f"frames/frame_{count}.jpg"
            cv2.imwrite(path, frame)
            frames.append(path)
        count += 1

    cap.release()
    return frames


async def analyse_video(video_path: str) -> dict:
    """
    Analyse a video for AI-generation signals by:
    1. Extracting frames and analysing with Gemini
    2. Extracting audio and transcribing with Deepgram
    3. Combining visual + audio analysis

    Args:
        video_path: Path to the video file on disk.

    Returns:
        dict: frame_descriptions (list), audio_transcript (str),
              ai_signals (str), frames_checked (int), error (str|None).
    """
    _error_result = {
        "frame_descriptions": [],
        "audio_transcript": "",
        "ai_signals": "",
        "frames_checked": 0,
        "error": None,
    }

    try:
        # Step 1: Extract frames
        frames = await asyncio.to_thread(extract_frames, video_path)
        if not frames:
            return {**_error_result, "error": "No frames extracted"}

        # Step 2: Analyse frames with Gemini
        frame_descriptions = []
        combined_ai_signals = []
        for frame_path in frames:
            try:
                result = await analyse_image_with_gemini(frame_path)
                frame_descriptions.append(result.get("caption", ""))
                if result.get("ai_signals"):
                    combined_ai_signals.append(result["ai_signals"])
            except Exception as e:
                logger.warning("[Video] Frame analysis failed for %s: %s", frame_path, e)
            finally:
                try:
                    if os.path.exists(frame_path):
                        os.remove(frame_path)
                except Exception:
                    pass

        # Step 3: Extract and transcribe audio
        audio_transcript = ""
        audio_path = None
        try:
            audio_path = tempfile.mktemp(suffix=".wav")
            from pydub import AudioSegment

            audio = await asyncio.to_thread(AudioSegment.from_file, video_path)
            await asyncio.to_thread(audio.export, audio_path, format="wav")
            transcript_result = await transcribe_audio(audio_path)
            audio_transcript = transcript_result.get("transcript", "")
        except Exception:
            logger.info("[Video] Audio extraction/transcription failed")
            audio_transcript = ""
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass

        return {
            "frame_descriptions": frame_descriptions,
            "audio_transcript": audio_transcript,
            "ai_signals": (
                " | ".join(combined_ai_signals)
                if combined_ai_signals
                else "No strong AI signals detected in frames"
            ),
            "frames_checked": len(frames),
            "error": None,
        }
    except Exception as e:
        logger.exception("[Video] Analysis failed: %s", e)
        return {**_error_result, "error": str(e)}

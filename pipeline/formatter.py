"""
pipeline/formatter.py — format_detection_message() — HTML only.

Formats detection results into user-friendly Telegram messages.
Uses parse_mode="HTML" — NEVER MarkdownV2.
"""

import html


def format_detection_message(
    content_type: str,
    verdict: str,
    is_safe: bool | None,
    explanation: str,
    is_harmful: bool = False,
    misinfo_type: str = "none",
    caption: str = "",
    ocr_text: str | None = None,
    transcript: str = "",
    ai_signals: str = "",
    frames_checked: int = 0,
) -> str:
    """
    Format a detection result into an HTML Telegram message.

    Args:
        content_type: One of 'text', 'image', 'audio', 'video'.
        verdict: Raw verdict label from GUARD.
        is_safe: Boolean safety result (True/False/None).
        explanation: Plain-language explanation from insights model.
        is_harmful: Whether content is flagged as harmful.
        misinfo_type: Misinformation type label (e.g. "fabricated_quote").
        caption: Image caption (for image content type).
        ocr_text: Extracted text from image OCR.
        transcript: Audio/video transcript text.
        ai_signals: Detected AI-generation signals.
        frames_checked: Number of video frames analysed.

    Returns:
        HTML string for Telegram (parse_mode="HTML").
    """
    # Determine verdict emoji and label
    if is_safe is False and is_harmful:
        verdict_emoji = "🚨"
        verdict_label = "Unsafe + Harmful"
    elif is_safe is False:
        verdict_emoji = "⚠️"
        verdict_label = "Unsafe"
    elif is_safe is True:
        verdict_emoji = "✅"
        verdict_label = "Safe"
    else:
        verdict_emoji = "❓"
        verdict_label = "Unclear"

    # Content type icon
    type_icons = {"text": "📝", "image": "🖼️", "audio": "🎤", "video": "🎬"}
    type_icon = type_icons.get(content_type, "📄")

    # Escape all dynamic content for HTML safety
    caption_safe = html.escape(caption or "")
    ocr_safe = html.escape(ocr_text) if ocr_text else None
    transcript_safe = html.escape(transcript or "")
    ai_signals_safe = html.escape(ai_signals or "")
    explanation_safe = html.escape(explanation or "")
    verdict_label_safe = html.escape(verdict_label)

    # Build HTML message
    lines = [
        f"{type_icon} <b>{html.escape(content_type.upper())} ANALYSIS</b>",
        f"{verdict_emoji} <b>Verdict</b>: {verdict_label_safe}",
    ]

    # Misinformation type display
    if misinfo_type and misinfo_type not in ("none", "unknown"):
        type_display = misinfo_type.replace("_", " ").title()
        lines.append(f"⚠️ <b>Type</b>: {html.escape(type_display)}")

    # Content preview section
    if content_type == "image":
        if caption_safe:
            lines.append(f"🔎 <b>Image Content</b>: {caption_safe[:150]}")
        if ocr_safe:
            lines.append(f"📖 <b>Detected Text</b>: <i>{ocr_safe[:150]}</i>")
        if ai_signals_safe:
            lines.append(f"⚠️ <b>Visual Signals</b>: {ai_signals_safe[:200]}")
    elif content_type == "audio":
        if transcript_safe:
            lines.append(f"📝 <b>Transcript</b>: <i>{transcript_safe[:200]}</i>")
    elif content_type == "video":
        if frames_checked:
            lines.append(f"🎞️ <b>Frames Analysed</b>: {frames_checked}")
        if transcript_safe:
            lines.append(
                f"📝 <b>Audio Transcript</b>: <i>{transcript_safe[:150]}</i>"
            )
        if ai_signals_safe:
            lines.append(f"⚠️ <b>Visual Signals</b>: {ai_signals_safe[:200]}")

    # Explanation
    lines.append("")
    lines.append("<b>Analysis</b>")
    clean_explanation = explanation_safe.strip()
    if len(clean_explanation) > 500:
        clean_explanation = clean_explanation[:497] + "..."
    lines.append(clean_explanation)

    # Footer
    lines.append("──────────────────────")
    lines.append("🤖 <i>Powered by SEA-LION GUARD + Gemini</i>")
    lines.append("<i>This is an automated analysis. Use your own judgement.</i>")

    return "\n".join(lines)

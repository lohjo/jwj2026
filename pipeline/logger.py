"""
pipeline/logger.py — log_to_clickhouse() — async, non-blocking.

Never raises. All exceptions are logged to stderr and swallowed.
"""

import hashlib
import logging
import sys
import uuid

from config import (
    CLICKHOUSE_HOST,
    CLICKHOUSE_PORT,
    CLICKHOUSE_USER,
    CLICKHOUSE_PASSWORD,
    CLICKHOUSE_DB,
    CLICKHOUSE_CONNECT_TIMEOUT,
    CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
    CLICKHOUSE_MAX_RETRIES,
)

logger = logging.getLogger(__name__)

# Lazy-initialised ClickHouse client (one per process)
_ch_client = None


def _get_ch_client():
    """Return a cached clickhouse-connect client. Never raises."""
    global _ch_client
    if _ch_client is not None:
        return _ch_client

    if not CLICKHOUSE_HOST or not CLICKHOUSE_PASSWORD:
        return None

    try:
        import clickhouse_connect

        _ch_client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DB,
            secure=True,
            connect_timeout=CLICKHOUSE_CONNECT_TIMEOUT,
            send_receive_timeout=CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
            query_retries=CLICKHOUSE_MAX_RETRIES,
        )
        return _ch_client
    except Exception:
        logger.exception("[ClickHouse] Failed to create client")
        return None


def log_to_clickhouse(row_dict: dict) -> dict:
    """
    Log a detection event to ClickHouse for real-time analytics.

    Safe to call via asyncio.to_thread(). Never raises — all exceptions
    are logged to stderr and swallowed.

    Args:
        row_dict: Dictionary with detection event data.

    Returns:
        {"status": "logged"} on success, {"status": "failed", "error": "..."} otherwise.
    """
    try:
        client = _get_ch_client()
        if client is None:
            return {"status": "failed", "error": "ClickHouse client unavailable"}

        # Map guard_verdict string to valid Enum value
        valid_verdicts = {"safe", "unsafe", "inconclusive", "error"}
        raw_verdict = (
            str(row_dict.get("guard_verdict", "error"))
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )
        guard_verdict = raw_verdict if raw_verdict in valid_verdicts else "error"

        # Map content_type to valid Enum value
        valid_types = {"text", "image", "audio", "video"}
        ct = str(row_dict.get("content_type", "text")).lower()
        content_type = ct if ct in valid_types else "text"

        # Hash user_id for privacy
        raw_uid = str(row_dict.get("user_id", "unknown"))
        hashed_uid = hashlib.sha256(raw_uid.encode()).hexdigest()[:16]

        row = [
            [
                uuid.uuid4(),
                hashed_uid,
                str(row_dict.get("session_id", "")),
                content_type,
                str(row_dict.get("source_language", "en")),
                str(row_dict.get("content_preview", ""))[:500],
                str(row_dict.get("guard_label", "")),
                guard_verdict,
                bool(row_dict.get("misinfo_detected", False)),
                str(row_dict.get("misinfo_type", "none")),
                bool(row_dict.get("manipulation_detected", False)),
                str(row_dict.get("manipulation_type", "none")),
                str(row_dict.get("explanation", "")),
                bool(row_dict.get("is_harmful", False)),
                int(row_dict.get("processing_ms", 0)),
                row_dict.get("model_versions") or {},
                str(row_dict.get("error_code", "none")),
            ]
        ]

        columns = [
            "event_id",
            "user_id",
            "session_id",
            "content_type",
            "source_language",
            "content_preview",
            "guard_label",
            "guard_verdict",
            "misinfo_detected",
            "misinfo_type",
            "manipulation_detected",
            "manipulation_type",
            "explanation",
            "is_harmful",
            "processing_ms",
            "model_versions",
            "error_code",
        ]

        client.insert(
            "detection_events",
            row,
            column_names=columns,
            settings={"async_insert": 1, "wait_for_async_insert": 0},
        )
        return {"status": "logged"}
    except Exception as exc:
        print(f"[ClickHouse] log_to_clickhouse failed: {exc}", file=sys.stderr)
        logger.exception("[ClickHouse] log_to_clickhouse failed")
        return {"status": "failed", "error": str(exc)}

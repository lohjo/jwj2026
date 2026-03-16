"""verify_integrations.py

Live integration checks using configured .env credentials.
This script intentionally avoids printing secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from pipeline.guard import run_guard_detection
from pipeline.insights import call_llm
from pipeline.logger import log_to_clickhouse
from pipeline.translator import detect_language, translate_from_english, translate_to_english


def _mask(value: str, keep: int = 4) -> str:
    if not value:
        return "<empty>"
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


async def _check_llm() -> tuple[bool, str]:
    text, llm_used = await call_llm("Reply with exactly: SENTINEL_OK", max_tokens=16)
    ok = bool(text)
    return ok, f"llm_used={llm_used}, response={text[:80]!r}"


async def _check_guard() -> tuple[bool, str]:
    result = await run_guard_detection("This is a short sample for detector health check.")
    label = result.get("label")
    ok = label not in {"api_error", "api_key_missing", "auth_error", "permission_denied", "timeout", "network_error"}
    return ok, f"label={label}, confidence={result.get('confidence')}"


async def _check_translation() -> tuple[bool, str]:
    zh_text = "这是一个用于翻译健康检查的简短句子。"
    lang = detect_language(zh_text * 2)
    en = await translate_to_english(zh_text, lang)
    back = await translate_from_english("SENTINEL translation check passed.", lang)
    ok = bool(en and back)
    return ok, f"detected={lang}, to_en_len={len(en)}, from_en_len={len(back)}"


def _check_clickhouse() -> tuple[bool, str]:
    row = {
        "user_id": "healthcheck",
        "session_id": "healthcheck",
        "content_type": "text",
        "source_language": "en",
        "content_preview": "health check row",
        "guard_label": "healthcheck",
        "guard_verdict": "inconclusive",
        "guard_confidence": 0.0,
        "misinfo_detected": False,
        "misinfo_type": "none",
        "manipulation_detected": False,
        "manipulation_type": "none",
        "explanation": "health check",
        "is_harmful": False,
        "processing_ms": 1,
        "model_versions": {"llm_used": "healthcheck"},
        "error_code": "none",
    }
    result = log_to_clickhouse(row)
    ok = result.get("status") == "logged"
    return ok, str(result)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run live API integration checks")
    parser.add_argument("--skip-clickhouse", action="store_true")
    args = parser.parse_args()

    checks: list[tuple[str, bool, str, float]] = []

    for name, fn in [
        ("llm", _check_llm),
        ("guard", _check_guard),
        ("translation", _check_translation),
    ]:
        start = time.time()
        ok, detail = await fn()
        checks.append((name, ok, detail, time.time() - start))

    if not args.skip_clickhouse:
        start = time.time()
        ok, detail = _check_clickhouse()
        checks.append(("clickhouse", ok, detail, time.time() - start))

    all_ok = True
    for name, ok, detail, sec in checks:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name} ({sec:.2f}s): {detail}")
        if not ok:
            all_ok = False

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""conftest.py — Set minimum required env vars for all tests.

config.py calls sys.exit() for any missing _required_ variable, so we must
inject stub values before importing any module that depends on config.
"""
import os

# Provide stub values for all _required_ config keys so that config.py
# can be imported without an installed .env file.
_REQUIRED_STUBS = {
    "TELEGRAM_TOKEN": "test-telegram-token",
    "OPENAI_API_KEY": "test-sealion-api-key",
    "GEMINI_API_KEY": "test-gemini-api-key",
}
for _k, _v in _REQUIRED_STUBS.items():
    os.environ.setdefault(_k, _v)

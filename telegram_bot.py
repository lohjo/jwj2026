import os
import sys
import logging
import asyncio
import importlib
import datetime
from pathlib import Path
from dotenv import load_dotenv

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters


# Initialize logging early so we can log .env loading and failures
logging.basicConfig(level=logging.INFO)

# Load .env early so TELEGRAM_TOKEN (or TELEGRAM_BOT_TOKEN) can be resolved once at import time
# Prefer an explicit path relative to the repository: project root (two levels up from this file).
_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)
logging.info(f"Loaded .env from: {_env_path} (exists={_env_path.exists()})")

# Fail fast if critical API keys are missing to avoid silent 401s from downstream clients
if not os.environ.get("OPENAI_API_KEY"):
    logging.error("OPENAI_API_KEY not found in .env — SEA-LION / OpenAI API calls will fail with 401")
    sys.exit(1)

TELEGRAM_TOKEN: str = os.environ.get("TELEGRAM_TOKEN", "")

# Module-level constants resolved once at startup
APP_NAME: str = "content-detection-agent"

# Use the project text detector
try:
    from image_detector import detect_fake_text
except Exception:
    detect_fake_text = None

# Import translation and detection utilities
# Handle hyphenated module name using importlib
detect_language = None
translate_to_english = None
translate_from_english = None
run_guard_detection = None
run_insights = None
log_to_clickhouse = None

try:
    # Try common import forms first (underscore variant)
    try:
        tools_module = importlib.import_module('ai_agent_adk.tools')
    except Exception:
        # Fallback: load the tools.py directly by path (handles hyphenated directory)
        try:
            import importlib.util
            pkg_dir = os.path.join(os.path.dirname(__file__), 'ai-agent-adk')
            tools_path = os.path.join(pkg_dir, 'tools.py')
            if os.path.exists(tools_path):
                spec = importlib.util.spec_from_file_location('ai_agent_adk.tools', tools_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                tools_module = module
            else:
                raise ImportError("ai-agent-adk/tools.py not found")
        except Exception:
            tools_module = None

    if tools_module:
        detect_language = getattr(tools_module, 'detect_language', None)
        translate_to_english = getattr(tools_module, 'translate_to_english', None)
        translate_from_english = getattr(tools_module, 'translate_from_english', None)
        run_guard_detection = getattr(tools_module, 'run_guard_detection', None)
        run_insights = getattr(tools_module, 'run_insights', None)
        log_to_clickhouse = getattr(tools_module, 'log_to_clickhouse', None)
    else:
        logging.warning("Could not import translation/detection utilities from ai-agent-adk.tools")
except Exception:
    logging.exception("Unexpected error while importing translation/detection utilities")


logging.basicConfig(level=logging.INFO)


async def hello(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass
    await update.message.reply_text(f'Hello {update.effective_user.first_name}')


async def echo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Echo command: /echo some text
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    args = context.args if hasattr(context, "args") else []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text("Usage: /echo <some text>")
        return
    await update.message.reply_text(text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle plain text messages with multilingual translation and detection pipeline.
    
    Translation-Detection Pipeline:
    1. Extract raw content
    2. Detect language
    3. Translate to English if needed
    4. Run detection on English text
    5. Run insights on English text
    6. Translate response back to user's language
    7. Send response
    """
    if not update.message or not update.message.text:
        return

    # Rate limiting and session reuse helpers are defined below
    raw_text = update.message.text

    user_id = str(update.effective_user.id)

    # FIX 8: rate limiting
    if not await check_rate_limit(user_id, update):
        return

    # FIX 1: typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    # FIX 6: get or create session
    session_id = await get_or_create_session(user_id)
    
    # Step 1: Extract raw content (already done above)
    
    # Step 2: Detect language
    # Guard against unreliable detection on very short strings
    if detect_language is not None and len(raw_text) >= 20:
        try:
            source_lang = detect_language(raw_text)
        except Exception:
            logging.exception("detect_language failed; defaulting to English")
            source_lang = "en"
    else:
        source_lang = "en"
        if detect_language is None:
            logging.warning("detect_language not available, defaulting to English")
        else:
            logging.info("Skipping language detection for short input; defaulting to English")
    
    # Step 3-7: Translation and detection pipeline
    if detect_fake_text is not None:
        await update.message.reply_text("Analyzing text, please wait...")
        try:
            # FIX 2: Translate to English if available (requires runner). If not available, skip.
            english_text = raw_text
            if source_lang != "en" and translate_to_english is not None:
                try:
                    # translate_to_english requires a runner; use module-level runner
                    runner = get_runner()
                    if runner is not None:
                        english_text = await translate_to_english(raw_text, source_lang, runner, user_id, session_id)
                    else:
                        logging.info("Runner not available; skipping translation to English")
                except Exception:
                    logging.exception("translate_to_english failed; using original text")

            # FIX 2: Detection pipeline (async guard + insights)
            detection_result = None
            insights_result = None
            if run_guard_detection is not None:
                detection_result = await run_guard_detection(english_text, source_lang=source_lang)

            if run_insights is not None:
                insights_result = await run_insights(english_text, detection_result or {})

            # FIX 3: Defer logging (background) and translate back concurrently where possible
            if log_to_clickhouse is not None:
                try:
                    asyncio.create_task(
                        asyncio.to_thread(
                            log_to_clickhouse,
                            user_id,
                            "text",
                            raw_text[:200],
                            (detection_result or {}).get('label', ''),
                            (detection_result or {}).get('confidence'),
                            (insights_result or {}).get('explanation', '')
                        )
                    )
                except Exception:
                    logging.exception("Failed to schedule clickhouse logging")

            # Translate explanation back if possible (may require runner)
            final_response = None
            if insights_result is not None and translate_from_english is not None and source_lang != "en":
                try:
                    runner = get_runner()
                    if runner is not None:
                        final_response = await translate_from_english(insights_result.get('explanation', ''), source_lang, runner, user_id, session_id)
                    else:
                        final_response = insights_result.get('explanation', '')
                except Exception:
                    logging.exception("translate_from_english failed; using English explanation")
                    final_response = insights_result.get('explanation', '')
            else:
                # Fallback: use detection_result label or detect_fake_text output
                if insights_result is not None:
                    final_response = insights_result.get('explanation', '')
                else:
                    # Run legacy detector as fallback
                    final_response = str(await asyncio.to_thread(detect_fake_text, english_text))

            await update.message.reply_text(final_response)
        except Exception as e:
            result = f"Detection error: {e}"
            logging.exception("Error in handle_text pipeline")
            await update.message.reply_text(result)
    else:
        await update.message.reply_text(f"You said: {raw_text}")


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # /detect <text>
    if detect_fake_text is None:
        await update.message.reply_text("Text detector is not available.")
        return

    # typing indicator
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    except Exception:
        pass

    args = context.args if hasattr(context, "args") else []
    text = " ".join(args).strip()
    if not text:
        await update.message.reply_text("Usage: /detect <text>")
        return
    await update.message.reply_text("Analyzing text, please wait...")
    user_id = str(update.effective_user.id)

    # Rate limit
    if not await check_rate_limit(user_id, update):
        return

    # Reuse session
    session_id = await get_or_create_session(user_id)

    try:
        # Run guard detection (async) if available
        if run_guard_detection is not None:
            detection_result = await run_guard_detection(text)
            insights_result = await run_insights(text, detection_result) if run_insights is not None else None
            # Schedule logging in background
            if log_to_clickhouse is not None:
                asyncio.create_task(asyncio.to_thread(log_to_clickhouse, user_id, "text", text[:200], detection_result.get('label', ''), detection_result.get('confidence'), (insights_result or {}).get('explanation', '')))
            final = (insights_result or {}).get('explanation') or str(detection_result)
        else:
            final = str(await asyncio.to_thread(detect_fake_text, text))
    except Exception as e:
        final = f"Detection error: {e}"

    await update.message.reply_text(final)


def get_token() -> str:
    # Accept either TELEGRAM_TOKEN or TELEGRAM_BOT_TOKEN (common name in .env)
    token = os.environ.get("TELEGRAM_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logging.error("Environment variable TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN is not set.")
        return ""
    return token


# -------------------- Session reuse + rate limiting helpers --------------------
session_service = InMemorySessionService()
user_sessions: dict[str, str] = {}

# Module-level runner — initialised once, reused across all handlers
_runner: Runner | None = None

def get_runner() -> Runner | None:
    global _runner
    if _runner is None:
        try:
            from ai_agent_adk.agent import root_agent
            _runner = Runner(
                app_name=APP_NAME,
                agent=root_agent,
                session_service=session_service,
            )
            logging.info("ADK runner initialised successfully")
        except Exception:
            logging.exception("Failed to initialise ADK runner")
    return _runner

async def get_or_create_session(user_id: str) -> str:
    if user_id not in user_sessions:
        session_id = f"session-{user_id}-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            await session_service.create_session(app_name="ai-fake-detector", user_id=user_id, session_id=session_id, state={})
        except Exception:
            logging.exception("Failed to create session; continuing without persistent session")
        user_sessions[user_id] = session_id
    return user_sessions[user_id]

user_last_request: dict[str, float] = {}
COOLDOWN_SECONDS = 3.0

async def check_rate_limit(user_id: str, update) -> bool:
    now = asyncio.get_event_loop().time()
    last = user_last_request.get(user_id, 0)
    if now - last < COOLDOWN_SECONDS:
        try:
            await update.message.reply_text("Please wait a moment before sending another request.")
        except Exception:
            pass
        return False
    user_last_request[user_id] = now
    return True



def main_cli():
    """Run the text detector from the command line in an interactive loop."""
    if detect_fake_text is None:
        print("Text detector is not available.", file=sys.stderr)
        sys.exit(1)

    # Check for non-interactive use first (text passed as arguments)
    args = [arg for arg in sys.argv[1:] if arg != '--cli']
    if args:
        text = " ".join(args).strip()
        if text:
            try:
                result = detect_fake_text(text)
                print("=== Analysis Result ===")
                print(result)
            except Exception as e:
                print(f"Detection error: {e}", file=sys.stderr)
        else:
            print("No text provided.", file=sys.stderr)
        sys.exit(0)

    # Interactive loop
    print("Entering interactive mode. Type 'quit' or 'exit' to stop.")
    while True:
        try:
            text = input("Enter text to analyze: ").strip()
            if not text:
                continue
            if text.lower() in ('quit', 'exit'):
                print("Exiting interactive mode.")
                break

            try:
                result = detect_fake_text(text)
                print("=== Analysis Result ===")
                print(result)
            except Exception as e:
                print(f"Detection error: {e}", file=sys.stderr)

        except (EOFError, KeyboardInterrupt):
            print("\nExiting interactive mode.")
            break


def start_bot():
    """Initializes and starts the Telegram bot."""
    token = TELEGRAM_TOKEN
    print(f"[DEBUG] Raw token value: '{token}'")  # will show quotes, spaces, newlines
    print(f"[DEBUG] Token length: {len(token)}") 
    if not token:
        logging.error("TELEGRAM_TOKEN not set — cannot start bot")
        sys.exit(1)

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("hello", hello))
    app.add_handler(CommandHandler("echo", echo_command))
    app.add_handler(CommandHandler("detect", detect_command))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text))

    logging.info("Starting Telegram bot polling...")
    app.run_polling()


if __name__ == "__main__":
    if '--cli' in sys.argv:
        main_cli()
    else:
        start_bot()
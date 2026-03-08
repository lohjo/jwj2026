from pathlib import Path
import sys

# Ensure project root is on sys.path so top-level modules can be imported
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
	sys.path.insert(0, str(project_root))

import telegram_bot

print('TELEGRAM_TOKEN ->', repr(telegram_bot.TELEGRAM_TOKEN))
print('OPENAI_API_KEY present ->', bool(telegram_bot.os.environ.get('OPENAI_API_KEY')))

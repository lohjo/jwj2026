from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os

# Candidate .env locations in order of preference
candidates = []
# current working directory (project root when running from repo)
candidates.append(Path.cwd() / '.env')
# repo relative to this file (one level up)
candidates.append(Path(__file__).resolve().parent.parent / '.env')
# ai_agent_adk package-local .env (often used in this repo)
candidates.append(Path(__file__).resolve().parent.parent / 'ai_agent_adk' / '.env')
# fallback to find_dotenv()
found = find_dotenv()
if found:
	candidates.append(Path(found))

seen = set()
loaded = False
for p in candidates:
	if p is None:
		continue
	p = p.resolve()
	if str(p) in seen:
		continue
	seen.add(str(p))
	print(f'Checking {p} (exists={p.exists()})')
	if p.exists():
		# Load and override any existing env vars in this process
		load_dotenv(dotenv_path=p, override=True)
		print(f'Loaded .env from: {p}')
		loaded = True
		break

if not loaded:
	print('No .env file found in candidate locations; environment may rely on system env vars')

print('TELEGRAM_TOKEN ->', os.getenv('TELEGRAM_TOKEN'))
print('TELEGRAM_BOT_TOKEN ->', os.getenv('TELEGRAM_BOT_TOKEN'))
print('OPENAI_API_KEY ->', bool(os.getenv('OPENAI_API_KEY')))

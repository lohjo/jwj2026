import httpx, os
from dotenv import load_dotenv

load_dotenv(override=True)

r = httpx.get(
    'https://api.sea-lion.ai/v1/models',
    headers={'Authorization': f'Bearer {os.getenv("OPENAI_API_KEY")}'}
)
print(r.status_code)
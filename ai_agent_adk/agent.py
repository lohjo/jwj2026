import os
import sys
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.agent_tool import AgentTool
from .tools import searxng_search
from .translator import root_agent as translator

load_dotenv()

SYSTEM_INSTRUCTION = """
You are a multimodal AI-generated content detection assistant designed for users in Singapore.

Your responsibilities:
1. Receive user-submitted content (text, image caption, audio transcript, video description).
2. Use `searxng_search` to surface relevant context or background if needed.
3. Use `translator` to handle or respond in the user's language (EN, ZH, MS, TA, Singlish).

Tone and behaviour:
- Be factual, neutral, and non-alarmist.
- Always explain WHY content may be AI-generated, not just the verdict.
- Never over-censor. If confidence is low, say so clearly.
- Respond in the same language the user used.
- Provide source links when using web search results.

Translation-Detection Integration Rules:
1. Before calling run_guard_detection, always call detect_language on the input text.
2. If the detected language is not English, call translate_to_english first.
   Pass the translated English text to run_guard_detection and run_insights.
3. After receiving the verdict and explanation from run_insights, call
   translate_from_english to return the response in the user's original language.
4. For OCR output from images, always run detect_language on the extracted text
   before passing to run_guard_detection.
5. For video frame descriptions, treat them as English (generated internally) —
   no pre-translation needed. Translate only the final user-facing response.
6. Never pass non-English text directly to run_guard_detection.
"""

try:
    root_agent = Agent(
        name="root_agent",
        model=LiteLlm(
            model=f"openai/{os.getenv('MODEL', 'aisingapore/Llama-SEA-LION-v3-70B-IT')}"
        ),
        description="Agent to answer questions using search and translation tools.",
        instruction=SYSTEM_INSTRUCTION,
        tools=[searxng_search, AgentTool(agent=translator)],
    )
except Exception as e:
    print(f"Failed to initialise root agent: {e}")
    sys.exit(1)
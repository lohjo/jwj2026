import asyncio
import datetime
import getpass
import os
import sys

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.adk.runners import Runner
from google.genai.types import Content, Part

# Import your custom tools from your tools.py script, or place in this script
try:
    from .tools import searxng_search
except ImportError:
    from tools import searxng_search

# Import your specialised agent from your agent's script, or place in this script
try:
    from translator import root_agent as translator
except ImportError:
    from translator import root_agent as translator

load_dotenv(override=True)

# Set up session service and identifiers
session_service = InMemorySessionService()
APP_NAME = "google-adk-agent"
SESSION_ID = f"session-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
USER_ID = f"user-{getpass.getuser()}"

async def setup_session():
   try:
      session = await session_service.create_session(
         app_name=APP_NAME,
         user_id=USER_ID,
         session_id=SESSION_ID,
         state={}
      )
      print(f"Session created with ID: {SESSION_ID} for user: {USER_ID}")
      return session
   except Exception as e:
      print(f"An error occurred while creating the session: {e}")
      sys.exit(1)

try:
   root_agent = Agent(
      name="root_agent",
      model=LiteLlm(
         model=f"openai/{os.getenv('MODEL', 'aisingapore/Llama-SEA-LION-v3-70B-IT')}"
      ),
      description="Agent to answer questions using translation tools.",
      instruction="You are a helpful assistant who answers questions in a concise and informative manner. " \
      "If you deem necessary, use the translator tool to help with translations. " \
      "Provide accurate and helpful responses.",
      tools=[AgentTool(agent=translator)],
   )
except Exception as e:
   print(f"An error occurred while creating the root agent: {e}")
   sys.exit(1)

async def main():
   try:
      await setup_session()
      print("🤖 Google ADK Agent CLI")
      print("Type your questions below. Type 'quit', 'exit', or press Ctrl+C to exit.")

      # Initialize the agent runner
      runner = Runner(
         app_name=APP_NAME,
         agent=root_agent,
         session_service=session_service,
         )

      while True:
         try:
            # Get user input
            user_input = input("\nUser: ").strip()

            # Check for exit commands
            if user_input.lower() in ['quit', 'exit', 'q']:
               print("Goodbye! 👋")
               break

            # Run the agent with the user input
            user_message = Content(role='user', parts=[Part(text=user_input)])

            agent_response_text = ""
            print("Bot: ", end="", flush=True)

            async for event in runner.run_async(
                  user_id=USER_ID,
                  session_id=SESSION_ID,
                  new_message=user_message
            ):
                  if event.content and event.content.parts:
                     text_chunk = event.content.parts[0].text
                     if text_chunk:
                        print(text_chunk, end="", flush=True)
                        if event.is_final_response():
                              agent_response_text += text_chunk

                  if event.is_final_response():
                     if not agent_response_text and event.content and event.content.parts and event.content.parts[0].text:
                        agent_response_text = event.content.parts[0].text
                     print()
                     break

            if not agent_response_text:
                  if event and event.error_message:
                     print(f"\nError: {event.error_message}")
                  else:
                     print("\n(No text response from bot)")

         except KeyboardInterrupt:
            print("\nExiting... Goodbye! 👋")
            break

   except Exception as e:
      print(f"An error occurred: {e}")
   finally:
      print("\nExiting the agent CLI. Goodbye! 👋")

if __name__ == "__main__":
   asyncio.run(main())
import os
from google import genai
from dotenv import load_dotenv

load_dotenv(dotenv_path="backend/.env")

def list_available_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("No API key found.")
        return

    try:
        client = genai.Client(api_key=api_key)
        print("Available Models:")
        for model in client.models.list():
            # Let's print the whole object or its name
            print(f"- Name: {model.name}")
            # If you want to see what's inside:
            # print(f"  Metadata: {model}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    list_available_models()

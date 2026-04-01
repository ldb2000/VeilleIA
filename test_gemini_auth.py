import os
from google import genai
from dotenv import load_dotenv

load_dotenv(dotenv_path="backend/.env")

def test_auth_api_key():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Test failed: No GEMINI_API_KEY found in backend/.env")
        return

    print("Testing with API Key from backend/.env...")
    try:
        client = genai.Client(api_key=api_key)
        
        print("Sending test prompt to Gemini (models/gemini-2.0-flash-lite)...")
        response = client.models.generate_content(
            model="gemini-2.0-flash-lite", 
            contents="Hello, this is a test from my AI Watch app. Are you working?"
        )
        
        print("\n--- Response from Gemini ---")
        print(response.text)
        print("----------------------------")
        print("\nSuccess! Your API Key is valid.")
        
    except Exception as e:
        print(f"\nAuth test failed: {e}")

if __name__ == "__main__":
    test_auth_api_key()

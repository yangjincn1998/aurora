import os

import dotenv
import openai

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=60)

print("Testing API connection with stream...")
print(f"Model: google/gemini-2.5-pro")

try:
    response = client.chat.completions.create(
        model="google/gemini-2.5-pro",
        messages=[{"role": "user", "content": "Say hello"}],
        stream=True,
        max_tokens=50
    )
    print("Stream created, reading chunks...")
    for i, chunk in enumerate(response):
        print(f"Chunk {i}: {chunk}")
        if i >= 5:
            print("Stopping after 5 chunks...")
            break
    print("Success!")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

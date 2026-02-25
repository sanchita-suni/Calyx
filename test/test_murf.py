"""Quick connectivity test for the Murf Falcon TTS API."""

import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

MURF_URL = "https://api.murf.ai/v1/speech/generate"

headers = {
    "api-key": os.getenv("MURF_API_KEY"),
    "Content-Type": "application/json",
    "Accept": "application/json"
}

payload = {
    "voiceId": os.getenv("MURF_VOICE_ID", "en-US-natalie"),
    "text": "Calyx systems are online and ready.",
    "style": "Conversational",
    "rate": 0,
    "pitch": 0
}

print(f"Testing Murf Falcon Connection...")
print(f"Using Voice ID: {payload['voiceId']}")

try:
    response = requests.post(MURF_URL, json=payload, headers=headers)

    if response.status_code == 200:
        print("SUCCESS: Murf Falcon responded!")
        with open("test_output.mp3", "wb") as f:
            f.write(response.content)
        print("Audio saved to 'test_output.mp3'.")
    else:
        print(f"ERROR {response.status_code}: {response.text}")

except Exception as e:
    print(f"CONNECTION ERROR: {e}")

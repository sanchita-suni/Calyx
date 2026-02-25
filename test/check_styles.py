"""Check available styles for a specific Murf voice."""

import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

URL = "https://api.murf.ai/v1/speech/voices"
headers = {"api-key": os.getenv("MURF_API_KEY"), "Accept": "application/json"}
MY_VOICE = os.getenv("MURF_VOICE_ID", "en-US-natalie")

print(f"Checking styles for: {MY_VOICE}")

try:
    response = requests.get(URL, headers=headers)
    voices = response.json()

    found = False
    for v in voices:
        if v["voiceId"] == MY_VOICE:
            print(f"\nVoice found!")
            print(f"  Name: {v['displayName']}")
            print(f"  Supported Styles: {v['availableStyles']}")
            found = True
            break

    if not found:
        print("Voice ID not found in library.")

except Exception as e:
    print(e)

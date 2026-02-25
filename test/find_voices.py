"""List all available Murf voices and their IDs."""

import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'backend', '.env'))

headers = {"api-key": os.getenv("MURF_API_KEY")}

try:
    response = requests.get("https://api.murf.ai/v1/speech/voices", headers=headers)
    response.raise_for_status()

    voices = response.json()

    print("Available Voices:")
    print("=" * 60)

    if isinstance(voices, dict) and "voices" in voices:
        for voice in voices["voices"]:
            print(f"  ID: {voice.get('voiceId', 'N/A'):20} | Name: {voice.get('name', 'N/A')}")
    elif isinstance(voices, list):
        for voice in voices:
            print(f"  ID: {voice.get('voiceId', 'N/A'):20} | Name: {voice.get('name', 'N/A')}")
    else:
        print("Full Response:", voices)

except requests.exceptions.RequestException as e:
    print(f"Error fetching voices: {e}")

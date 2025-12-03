import os
import requests
from dotenv import load_dotenv

load_dotenv()

URL = "https://api.murf.ai/v1/speech/voices"
headers = {"api-key": os.getenv("MURF_API_KEY"), "Accept": "application/json"}
MY_VOICE = os.getenv("MURF_VOICE_ID")

print(f"🔎 Checking styles for: {MY_VOICE}")

try:
    response = requests.get(URL, headers=headers)
    voices = response.json()
    
    found = False
    for v in voices:
        if v["voiceId"] == MY_VOICE:
            print(f"\n✅ VOICE FOUND!")
            print(f"• Name: {v['displayName']}")
            print(f"• Supported Styles: {v['availableStyles']}") # <--- THIS IS THE KEY
            found = True
            break
            
    if not found:
        print("❌ Voice ID not found in library.")

except Exception as e:
    print(e)
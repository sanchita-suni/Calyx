import requests

API_KEY = "ap2_3d1e33b9-b566-4f62-bb49-4488f76ab6d7"  # Replace with your actual key

headers = {
    "api-key": API_KEY
}

try:
    response = requests.get("https://api.murf.ai/v1/speech/voices", headers=headers)
    response.raise_for_status()
    
    voices = response.json()
    
    print("✅ Available Voices:")
    print("=" * 60)
    
    # Parse and display all voices
    if isinstance(voices, dict) and "voices" in voices:
        for voice in voices["voices"]:
            print(f"  ID: {voice.get('voiceId', 'N/A'):20} | Name: {voice.get('name', 'N/A')}")
    elif isinstance(voices, list):
        for voice in voices:
            print(f"  ID: {voice.get('voiceId', 'N/A'):20} | Name: {voice.get('name', 'N/A')}")
    else:
        print("Full Response:", voices)
        
except requests.exceptions.RequestException as e:
    print(f"❌ Error fetching voices: {e}")
    print(f"Status Code: {e.response.status_code if hasattr(e, 'response') else 'N/A'}")

🛡️ Calyx: The Emotionally Adaptive Crisis Companion

🚨 The Problem
Standard voice assistants are loud, robotic, and oblivious to context. In a life-threatening situation—like an intruder, domestic violence, or a medical collapse—you cannot risk speaking to a cheerful bot that shouts, "I found three results for..."

You need a silent guardian that listens to your environment, understands covert speech, and acts when you can't.

💡 The Solution: Calyx
Calyx is an AI First Responder that bridges the gap between a panic button and 911. It uses Murf Falcon's ultra-low latency and emotional range to adapt its voice, tone, and strategy in real-time.

🔥 Key Features

🤫 Stealth Mode (Whisper Protocol):
Detects if you are whispering or hiding.
Switches Murf Falcon to a low-volume, calm whisper to guide you without giving away your position.

🍕 Pizza Ops (Covert Dispatch):
Caught in a hostage situation? Or a situation where you can't talk freely? Order a Pizza.
Calyx acts as a pizza dispatcher but decodes your order:
"Spicy" = Armed Threat
"Extra Napkins" = Injured
It gathers intel without alerting the attacker and relays it your emergency contact.

📞 Guardian Relay (Live Telephony):
If you go silent, Calyx takes over. It triggers a real phone call (via Twilio) to your emergency contact.
The AI speaks to them on your behalf, explains the situation, and sends your Live GPS Location.

🎭 Decoy Protocol (Voice Morphing):
Need to deter a threat while walking alone? Say "Hey Dad".
Calyx simulates a fake phone call with a deep, authoritative male voice.
It holds a realistic conversation with you ("I'm just around the corner") to make it look like help is seconds away, while reaching out to your emergency contact.

⚡ Tech Stack (Built for Speed)
Voice Generation: Murf Falcon TTS - The heart of Calyx. Used for instant (<300ms) voice switching (Whisper/Promo/Calm).
Intelligence: Groq(Llama 3) - Ultra-fast inference to decode context ("Pizza" -> "Hostage") in milliseconds.
Hearing: Deepgram Nova-2 - Real-time speech-to-text that captures whispers and background noise.
Telephony: Twilio Media Streams - Connects the AI Brain directly to the global telephone network for live calls.
Backend: Python(FastAPI) - Asynchronous WebSocket server handling audio streams.

🚀 How It Works (Architecture)
1. Listen: User audio is streamed via WebSockets to Deepgram.
2. Think: Groq analyzes the text for triggers (e.g., "Order Pizza") and outputs control signals ([SIGNAL:CALL], [MODE:STEALTH]).
3. Act:
  -If [MODE:STEALTH]: Murf Falcon generates audio in "Calm" style with low pitch.
  -If [SIGNAL:CALL]: Twilio dials the emergency contact.
4. Bridge: The phone call connects to the same AI brain, allowing the Emergency Contact to ask questions ("Is she hurt?") which the AI answers based on the user's context.

🛠️ Installation & Setup
1. Clone the Repository:
   git clone https://github.com/yourusername/calyx-voice-agent.git ;
   cd calyx-voice-agent

2. Install Dependencies:
   pip install -r requirements.txt

3. Configure Environment Variables Create a .env file in the root directory:
    Follow the format in the .env.example file

4. Run the Server:
   python main.py (or) uvicorn main:app --reload

5. Access the app:
   Open http://localhost:8000


🏆 Why Murf Falcon?
Calyx relies on Murf Falcon because standard TTS allows for neither the speed required for a crisis nor the range required for deception.
Latency: Falcon's streaming capability allows Calyx to interrupt and respond faster than a human (crucial for "Decoy" mode).
Range: Only Falcon could switch from a terrified whisper to a commanding male voice instantly, making the "Decoy Protocol" possible.

🎥 Demo Video
https://drive.google.com/file/d/1Z4EToGAONqq9xTrymd9z1OFLqm0lkfW4/view?usp=sharing

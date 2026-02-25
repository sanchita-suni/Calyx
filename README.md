# Calyx - Emotionally Adaptive Crisis Companion

> **2nd Place - Murf Voice Agent Hackathon @ IIT Bombay Techfest 2025**

Calyx is a real-time AI safety agent that adapts its voice, tone, and strategy to match crisis situations. It uses **Murf Falcon** for ultra-low-latency voice generation, enabling real-time persona switching - from a calm whisper to a commanding male voice - in under 300ms.

## The Problem

Standard voice assistants are loud, robotic, and context-blind. In a life-threatening situation, you can't risk a cheerful bot shouting responses. You need a **silent guardian** that listens, understands covert speech, and acts when you can't.

## How It Works

```
User speaks  -->  Deepgram Nova-2 (STT)  -->  Groq Llama 3.1 (LLM)  -->  Murf Falcon (TTS)  -->  Audio back to user
                  Real-time transcription     Crisis classification        Adaptive voice            <300ms latency
                                              Mode/signal detection        Style/pitch/rate switching
```

Three concurrent async tasks run per session:
1. **receive_cmds** - Handles incoming audio, text, GPS, and SOS signals
2. **process_voice_ai** - STT -> LLM -> TTS voice pipeline
3. **process_text_ai** - Text-only mode for covert/silent scenarios

## Key Features

### Stealth Mode
Detects whispering or hiding. Switches Murf Falcon to `Meditative` style with low pitch (-10) and slow rate (-15) to respond without giving away your position.

### Pizza Ops (Covert Dispatch)
Can't speak freely? "Order a pizza." Calyx acts as a pizza dispatcher while decoding your order:
- "Spicy" = Armed threat
- "Extra napkins" = Injured

It gathers intel without alerting an attacker, then relays the decoded situation to your emergency contact.

### Decoy Protocol (Voice Morphing)
Say "Hey Dad" and Calyx simulates a phone call with `en-IN-aarav` (deep male voice) at pitch -5, acting as a protective family member: *"Hey, where are you? I'm just around the corner."* Meanwhile, it contacts your real emergency contact.

### Guardian Relay (Live Telephony)
If you go silent for 10 seconds, Calyx:
1. Sends SMS with your GPS location to all emergency contacts
2. Initiates a **live AI phone call** to your primary contact via Twilio
3. The AI explains the situation and answers questions on your behalf

### Evidence Vault
Auto-generates timestamped PDF transcripts with GPS coordinates for post-incident documentation.

## Murf Falcon Integration

Calyx uses two Murf API endpoints:

| Endpoint | Use Case | Why |
|----------|----------|-----|
| `/v1/speech/stream` | Browser audio (24kHz MP3) | Falcon model streaming for <300ms first-byte latency |
| `/v1/speech/generate` | Phone audio (8kHz WAV) | Twilio requires specific sample rate for telephony |

**10 voice profiles** are defined in [`voice_profiles.py`](backend/models/voice_profiles.py), each mapping to a crisis mode with specific `style`, `rate`, and `pitch` values:

| Profile | Voice | Style | Rate | Pitch | Use Case |
|---------|-------|-------|------|-------|----------|
| DEFAULT | en-US-natalie | Conversational | 0 | 0 | Normal companion |
| STEALTH | en-US-natalie | Meditative | -15 | -10 | Whisper-quiet |
| DECOY_BROTHER | en-IN-aarav | Conversational | +5 | -5 | Protective male voice |
| CALM | en-US-natalie | Meditative | -20 | -5 | Panic attack grounding |
| URGENT | en-US-natalie | Conversational | +10 | +5 | Action-oriented urgency |

The LLM outputs inline control signals (`[MODE:STEALTH]`, `[SIGNAL:CALL]`) that trigger voice profile switches in real-time, without re-initializing the TTS pipeline.

## Project Structure

```
Calyx/
├── backend/
│   ├── main.py                          # FastAPI server, WebSocket endpoints
│   ├── models/
│   │   ├── state.py                     # CalyxState, LocationStore, UserProfile, ConversationContext
│   │   └── voice_profiles.py            # Murf voice configurations per crisis mode
│   ├── services/
│   │   ├── murf_service.py              # Murf Falcon TTS (streaming + phone audio)
│   │   ├── groq_service.py              # Groq LLM (crisis classification + prompts)
│   │   ├── deepgram_service.py          # Deepgram Nova-2 STT
│   │   ├── guardian_relay.py            # Multi-contact emergency notification (Twilio)
│   │   ├── twilio_service.py            # Phone call audio encoding/decoding
│   │   └── evidence_vault.py            # PDF incident report generation
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   └── index.html                       # Full UI (chat, visualizer, covert screens, SOS)
├── test/
│   ├── test_murf.py                     # Murf API connectivity test
│   ├── find_voices.py                   # List available Murf voices
│   └── check_styles.py                  # Check styles for a voice
└── README.md
```

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Fill in your API keys
```

You'll need:
- **Murf API key** - [murf.ai/dashboard](https://murf.ai/dashboard/api-keys)
- **Groq API key** - [console.groq.com](https://console.groq.com/keys)
- **Deepgram API key** - [console.deepgram.com](https://console.deepgram.com/)
- **Twilio credentials** - [console.twilio.com](https://console.twilio.com/) (for Guardian Relay)
- **Ngrok domain** - For Twilio phone call WebSocket tunnel

### 3. Run

```bash
python main.py
```

Open [http://localhost:8000](http://localhost:8000)

### 4. For Phone Calls (Guardian Relay)

```bash
# In a separate terminal
ngrok http 8000
# Copy the domain to NGROK_DOMAIN in .env
```

## Tech Stack

| Component | Technology | Role |
|-----------|-----------|------|
| **Voice** | Murf Falcon | Streaming TTS with real-time style switching |
| **Intelligence** | Groq (Llama 3.1 8B) | Ultra-fast crisis classification and response |
| **Hearing** | Deepgram Nova-2 | Real-time speech-to-text (browser + phone) |
| **Telephony** | Twilio Media Streams | Live AI phone calls to emergency contacts |
| **Backend** | FastAPI + Uvicorn | Async WebSocket server |
| **Frontend** | Vanilla JS + Tailwind | Web Audio API, Geolocation, WebSocket client |

## Demo

### [Full Walkthrough (with Voice-Over)](https://drive.google.com/file/d/1Z4EToGAONqq9xTrymd9z1OFLqm0lkfW4/view?usp=sharing)

Narrated demo covering all features end-to-end: Stealth Mode, Pizza Ops covert dispatch, Decoy Protocol voice morphing, Guardian Relay live telephony, and Evidence Vault PDF generation. Recorded during initial development before latency optimizations.

---

### [Sub-Second Latency Demo](https://drive.google.com/file/d/1RMq0FrHZyLN2vkc812Hg_rxJRSm6lXWG/view?usp=sharing)

After optimizing the STT -> LLM -> TTS pipeline, the full voice loop runs in under one second. This demo captures the latency improvements in action—real-time voice profile switching and crisis response with minimal delay. No voice-over; raw interaction only.

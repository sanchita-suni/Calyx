"""
Voice profile configurations for Murf Falcon TTS.

Each profile maps to a specific crisis scenario, adjusting voice identity,
speaking style, rate, and pitch to match the emotional context.
Murf Falcon's style/rate/pitch controls enable real-time voice adaptation
without switching models or re-initializing the TTS pipeline.
"""

SAFE_WORD = "blueberries"

VOICE_PROFILES = {
    "DEFAULT": {
        "voice_id": "en-US-natalie",
        "style": "Conversational",
        "rate": 0,
        "pitch": 0,
        "description": "Warm, supportive companion"
    },
    "STEALTH": {
        "voice_id": "en-US-natalie",
        "style": "Meditative",
        "rate": -15,
        "pitch": -10,
        "description": "Whisper-quiet, minimal"
    },
    "DECOY_BROTHER": {
        "voice_id": "en-IN-aarav",
        "style": "Conversational",
        "rate": 5,
        "pitch": -5,
        "description": "Protective older brother"
    },
    "DECOY_FATHER": {
        "voice_id": "en-IN-aarav",
        "style": "Conversational",
        "rate": 0,
        "pitch": -15,
        "description": "Concerned father figure"
    },
    "DECOY_FRIEND": {
        "voice_id": "en-IN-aarav",
        "style": "Conversational",
        "rate": 5,
        "pitch": 0,
        "description": "Male friend checking in"
    },
    "COVERT": {
        "voice_id": "en-US-natalie",
        "style": "Conversational",
        "rate": 5,
        "pitch": 0,
        "description": "Casual cover conversation"
    },
    "CALM": {
        "voice_id": "en-US-natalie",
        "style": "Meditative",
        "rate": -20,
        "pitch": -5,
        "description": "Therapeutic, grounding"
    },
    "MEDICAL": {
        "voice_id": "en-US-natalie",
        "style": "Conversational",
        "rate": -5,
        "pitch": 0,
        "description": "Clear medical instructions"
    },
    "URGENT": {
        "voice_id": "en-US-natalie",
        "style": "Conversational",
        "rate": 10,
        "pitch": 5,
        "description": "Action-oriented urgency"
    },
    "DISPATCHER": {
        "voice_id": "en-US-natalie",
        "style": "Conversational",
        "rate": 5,
        "pitch": 0,
        "description": "Professional emergency dispatcher"
    }
}

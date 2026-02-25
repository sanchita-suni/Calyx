"""
Core state management for Calyx.

Manages conversation context, user profiles, GPS location tracking,
and the adaptive mode system that drives voice profile switching.
"""

import datetime
from typing import List, Dict, Optional

from .voice_profiles import VOICE_PROFILES


class UserProfile:
    """Stores user's name and emergency contacts for the active session."""

    _name = "User"
    _contacts: List[Dict] = []

    @classmethod
    def set_name(cls, name: str):
        cls._name = name.strip() if name else "User"
        print(f">>> [PROFILE] User name: {cls._name}")

    @classmethod
    def get_name(cls) -> str:
        return cls._name

    @classmethod
    def set_contacts(cls, contacts: List[Dict]):
        cls._contacts = contacts
        print(f">>> [PROFILE] Contacts: {len(contacts)}")

    @classmethod
    def get_contacts(cls) -> List[Dict]:
        return cls._contacts

    @classmethod
    def get_primary_contact(cls) -> Optional[Dict]:
        return cls._contacts[0] if cls._contacts else None


class LocationStore:
    """GPS coordinate store, updated from the browser's Geolocation API."""

    _lat = None
    _lng = None
    _raw = "Unknown Location"

    @classmethod
    def update(cls, coords):
        if not coords:
            return
        if not isinstance(coords, str):
            coords = str(coords)
        clean = coords.strip()
        if "," in clean:
            parts = clean.split(",")
            if len(parts) >= 2:
                try:
                    cls._lat = float(parts[0].strip())
                    cls._lng = float(parts[1].strip())
                    cls._raw = f"{cls._lat},{cls._lng}"
                    print(f">>> [GPS] Updated: lat={cls._lat}, lng={cls._lng}")
                except ValueError as e:
                    print(f">>> [GPS] ValueError: {e}")

    @classmethod
    def get(cls) -> str:
        return cls._raw

    @classmethod
    def get_coords(cls) -> tuple:
        return (cls._lat, cls._lng)

    @classmethod
    def get_map_link(cls) -> str:
        if cls._lat is not None and cls._lng is not None:
            return f"https://maps.google.com/?q={cls._lat},{cls._lng}"
        return "Location unavailable"


class ConversationContext:
    """Tracks conversation history, threat assessment, and incident details."""

    def __init__(self):
        self.messages: List[Dict] = []
        self.threat_level = 0
        self.situation_summary = ""
        self.detected_scenario = None
        self.key_facts = {
            "weapons": None,
            "injuries": None,
            "attacker_description": None,
            "location_details": None,
            "time_critical": False,
            "coercion_detected": False,
            "code_used": None,
        }
        self.user_state = {
            "emotional": "unknown",
            "physical": "unknown",
            "can_speak": True,
        }
        self.safe_word_verified = False
        self.contacts_notified = []
        self.first_responder = None

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.datetime.now().isoformat()
        })

    def get_recent_context(self, n: int = 15) -> str:
        recent = self.messages[-n:] if len(self.messages) > n else self.messages
        return "\n".join([f"{m['role'].upper()}: {m['content']}" for m in recent])

    def generate_emergency_briefing(self) -> str:
        parts = []
        user_name = UserProfile.get_name()

        if self.detected_scenario:
            parts.append(f"SCENARIO: {self.detected_scenario}")

        threat = "LOW" if self.threat_level < 4 else "MEDIUM" if self.threat_level < 7 else "HIGH"
        parts.append(f"THREAT LEVEL: {threat}")

        if self.key_facts["weapons"]:
            parts.append(f"WEAPONS: {self.key_facts['weapons']}")
        if self.key_facts["injuries"]:
            parts.append(f"INJURIES: {self.key_facts['injuries']}")
        if self.key_facts["coercion_detected"]:
            parts.append("WARNING: Possible coercion")
        if self.key_facts["code_used"]:
            parts.append(f"COVERT CODE: {self.key_facts['code_used']}")

        parts.append(f"USER: {user_name} - {self.user_state['emotional']}")

        if self.situation_summary:
            parts.append(f"SITUATION: {self.situation_summary}")

        return " | ".join(parts) if parts else f"{user_name} triggered emergency SOS."

    def generate_sms_briefing(self, lat: float = None, lng: float = None) -> str:
        user_name = UserProfile.get_name()
        lines = ["CALYX EMERGENCY ALERT"]
        lines.append(f"{user_name} needs your help!")

        if self.situation_summary:
            lines.append(f"\n{self.situation_summary[:120]}")
        elif self.detected_scenario:
            lines.append(f"\nType: {self.detected_scenario.replace('_', ' ').title()}")

        if lat is None or lng is None:
            lat, lng = LocationStore.get_coords()

        if lat is not None and lng is not None:
            lines.append(f"\nLOCATION:")
            lines.append(f"https://maps.google.com/maps?q={lat},{lng}")
        else:
            raw_loc = LocationStore.get()
            if raw_loc and raw_loc != "Unknown Location":
                lines.append(f"\nLocation: {raw_loc}")

        lines.append("\nCall is connecting you to Calyx AI for more info.")
        return "\n".join(lines)


class CalyxState:
    """Central state object shared across all services in a session."""

    def __init__(self):
        self.mode = "DEFAULT"
        self.voice_profile = VOICE_PROFILES["DEFAULT"]
        self.mode_changed = True
        self.interrupted = False
        self.is_phone_call = False
        self.incident_context = ""
        self.call_active = False
        self.silent_mode = False
        self.covert_screen_active = False
        self.conversation_context = ConversationContext()
        self.decoy_persona = None
        self.latency_samples = []

    @property
    def voice_id(self):
        return self.voice_profile["voice_id"]

    @property
    def style(self):
        return self.voice_profile["style"]

    @property
    def rate(self):
        return self.voice_profile["rate"]

    @property
    def pitch(self):
        return self.voice_profile["pitch"]

    def signal_interruption(self):
        self.interrupted = True

    def reset_interruption(self):
        self.interrupted = False

    def add_latency_sample(self, ms: int):
        self.latency_samples.append(ms)
        if len(self.latency_samples) > 20:
            self.latency_samples = self.latency_samples[-20:]

    def get_avg_latency(self) -> int:
        if not self.latency_samples:
            return 0
        return int(sum(self.latency_samples) / len(self.latency_samples))

    def update_incident_context(self, text):
        self.incident_context = text
        self.conversation_context.situation_summary = text

    def set_mode(self, mode: str, decoy_persona: str = None):
        if self.mode != mode or self.decoy_persona != decoy_persona:
            self.mode = mode
            self.decoy_persona = decoy_persona

            if mode == "STEALTH":
                self.voice_profile = VOICE_PROFILES["STEALTH"]
                self.silent_mode = True
            elif mode == "DECOY":
                if decoy_persona == "brother":
                    self.voice_profile = VOICE_PROFILES["DECOY_BROTHER"]
                elif decoy_persona == "father":
                    self.voice_profile = VOICE_PROFILES["DECOY_FATHER"]
                else:
                    self.voice_profile = VOICE_PROFILES["DECOY_FRIEND"]
            elif mode == "COVERT":
                self.voice_profile = VOICE_PROFILES["COVERT"]
            elif mode == "CALM":
                self.voice_profile = VOICE_PROFILES["CALM"]
            elif mode == "MEDICAL":
                self.voice_profile = VOICE_PROFILES["MEDICAL"]
            elif mode == "URGENT":
                self.voice_profile = VOICE_PROFILES["URGENT"]
            else:
                self.voice_profile = VOICE_PROFILES["DEFAULT"]

            self.mode_changed = True
            print(f">>> [STATE] Mode: {mode}, Voice: {self.voice_profile['description']}")

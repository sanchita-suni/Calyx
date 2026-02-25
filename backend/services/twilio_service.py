"""
Twilio audio encoding/decoding for phone call media streams.

Converts between Twilio's mulaw-encoded payloads and raw PCM
so audio can flow between the phone network and our AI pipeline.
"""

import base64
import audioop

from models import CalyxState


class TwilioPhoneService:
    def __init__(self, state: CalyxState):
        self.state = state
        self.stream_sid = None

    async def process_incoming_audio(self, payload):
        """Decode Twilio mulaw payload to linear PCM."""
        try:
            return audioop.ulaw2lin(base64.b64decode(payload), 2)
        except:
            return None

    def create_outgoing_audio_msg(self, raw_pcm: bytes):
        """Encode PCM audio to Twilio mulaw media message."""
        try:
            if len(raw_pcm) % 2 != 0:
                raw_pcm = raw_pcm[:-1]
            payload = base64.b64encode(audioop.lin2ulaw(raw_pcm, 2)).decode("utf-8")
            return {"event": "media", "streamSid": self.stream_sid, "media": {"payload": payload}}
        except:
            return None

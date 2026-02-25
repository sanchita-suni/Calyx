"""
Murf Falcon Text-to-Speech service.

Uses two Murf API endpoints:
  - /v1/speech/stream  (Falcon model) for ultra-low-latency browser audio
  - /v1/speech/generate for phone-quality WAV output (Twilio)

Voice profiles (style, rate, pitch) are dynamically read from CalyxState,
enabling real-time voice switching across crisis modes without re-init.
"""

import os
import re
import time
import asyncio
import httpx
from typing import AsyncGenerator

from models import CalyxState


class MurfService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("MURF_API_KEY")
        self.stream_url = "https://api.murf.ai/v1/speech/stream"
        self.generate_url = "https://api.murf.ai/v1/speech/generate"
        self.state = state
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=2.0), http2=True)

    async def stream_audio(self, text_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        """Collect full LLM response, then stream audio sentence by sentence."""
        full_text = ""

        async for chunk in text_stream:
            if isinstance(chunk, bytes):
                yield chunk  # Pass through signal bytes (SIGNAL_CALL, etc.)
                continue
            full_text += chunk

        if self.state.interrupted or not full_text.strip():
            return

        clean_text = full_text.strip()
        sentences = re.split(r'(?<=[.!?])\s+', clean_text)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 3:
                continue
            if sentence[-1] not in '.!?':
                sentence += '.'

            audio, duration = await self._gen_audio_with_duration(sentence)
            if audio:
                yield audio
                await asyncio.sleep(duration + 0.1)

    async def _gen_audio_with_duration(self, text: str) -> tuple:
        """Generate audio via Falcon streaming and estimate playback duration."""
        clean = text.strip()
        if not clean:
            return None, 0

        clean = re.sub(r'\[?MODE:\w+(?::\w+)?\]?\s*', '', clean, flags=re.I)
        clean = re.sub(r'\[?SIGNAL:\w+\]?\s*', '', clean, flags=re.I)
        clean = clean.strip()

        if len(clean) < 2:
            return None, 0

        clean = self._filter_hallucinations(clean)
        if len(clean) < 2:
            return None, 0

        t0 = time.time()
        profile = self.state.voice_profile

        try:
            async with self.http.stream(
                "POST",
                self.stream_url,
                json={
                    "text": clean,
                    "voiceId": profile["voice_id"],
                    "style": profile["style"],
                    "rate": profile["rate"],
                    "pitch": profile["pitch"],
                    "model": "FALCON",
                    "format": "MP3",
                    "sampleRate": 24000,
                },
                headers={"api-key": self.api_key, "Content-Type": "application/json"}
            ) as r:
                if r.status_code == 200:
                    chunks = [c async for c in r.aiter_bytes()]
                    audio = b''.join(chunks)
                    latency = int((time.time() - t0) * 1000)
                    self.state.add_latency_sample(latency)

                    rate_factor = 1.0 - (profile["rate"] / 100)
                    chars_per_sec = 12.5 * rate_factor
                    duration = len(clean) / chars_per_sec

                    print(f"[MURF] {latency}ms ({duration:.1f}s): {clean[:30]}...")
                    return audio, duration
        except Exception as e:
            print(f"[MURF] Error: {e}")
        return None, 0

    def _filter_hallucinations(self, text: str) -> str:
        """Remove false capability claims the LLM might generate."""
        hallucination_patterns = [
            r"(?:I'm |I am |I will |I can |I'll |let me |going to )(?:track|locate|find|trace|ping|monitor|watch|see|view|access|hack|unlock|control|dispatch|send (?:police|ambulance|help)|call (?:911|police|ambulance|emergency services))",
            r"(?:tracking|locating|finding|tracing|pinging|monitoring|dispatching|sending help)",
            r"(?:I've |I have )(?:sent|dispatched|called|alerted) (?:police|ambulance|emergency services|911|help)",
            r"authorities (?:are|have been) (?:notified|alerted|dispatched|on (?:the |their )?way)",
            r"help is on the way",
            r"I(?:'m| am) (?:alerting|contacting|calling) (?:emergency services|police|911)",
        ]

        filtered = text
        for pattern in hallucination_patterns:
            filtered = re.sub(pattern, "", filtered, flags=re.IGNORECASE)

        filtered = re.sub(r'\s+', ' ', filtered).strip()
        filtered = re.sub(r'\s+([.,!?])', r'\1', filtered)
        return filtered if filtered else text

    async def generate_phone_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        """Generate 8kHz WAV audio for Twilio phone calls, sentence by sentence."""
        clean = text.strip()
        if not clean:
            return

        sentences = re.split(r'(?<=[.!?])\s+', clean)

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 3:
                continue

            t0 = time.time()
            try:
                r = await self.http.post(
                    self.generate_url,
                    json={
                        "voiceId": "en-US-natalie",
                        "style": "Conversational",
                        "text": sentence,
                        "rate": 5,
                        "pitch": 0,
                        "sampleRate": 8000,
                        "format": "WAV",
                        "channelType": "MONO"
                    },
                    headers={
                        "api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    }
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("audioFile"):
                        wav = await self.http.get(data["audioFile"])
                        pcm = wav.content[44:] if len(wav.content) > 44 else wav.content
                        print(f"[MURF Phone] {int((time.time()-t0)*1000)}ms: {sentence[:30]}...")
                        yield pcm
                        await asyncio.sleep(0.25)
            except Exception as e:
                print(f"[MURF Phone] Error: {e}")

    async def close(self):
        await self.http.aclose()

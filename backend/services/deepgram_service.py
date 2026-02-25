"""
Deepgram Nova-2 Speech-to-Text service.

Handles real-time audio transcription over WebSocket for both
browser sessions (16kHz) and Twilio phone calls (8kHz mulaw).
"""

import os
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

from models import CalyxState


class DeepgramService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.state = state
        self.client = DeepgramClient(self.api_key)
        self.connection = None
        self.is_connected = False

    async def start(self, callback, is_phone=False):
        try:
            mode = 'phone' if is_phone else 'user'
            print(f"[DEEPGRAM] Connecting ({mode})...")

            self.client = DeepgramClient(self.api_key)
            self.connection = self.client.listen.asyncwebsocket.v("1")

            async def on_msg(sender, result, **kwargs):
                try:
                    text = result.channel.alternatives[0].transcript
                    if text and result.is_final:
                        print(f"[{'Phone' if is_phone else 'User'}]: {text}")
                        if not is_phone:
                            self.state.signal_interruption()
                        await callback(text)
                except Exception as e:
                    print(f"[DEEPGRAM] Transcript error: {e}")

            self.connection.on(LiveTranscriptionEvents.Transcript, on_msg)

            opts = LiveOptions(
                model="nova-2-phonecall" if is_phone else "nova-2",
                language="en-US",
                encoding="linear16",
                sample_rate=8000 if is_phone else 16000,
                channels=1,
                interim_results=False,
                endpointing=200 if is_phone else 300,
            )

            self.is_connected = await self.connection.start(opts)
            if self.is_connected:
                print(f"[DEEPGRAM] Ready ({mode})")
                return True

        except Exception as e:
            print(f"[DEEPGRAM] Error: {e}")

        return False

    async def send_audio(self, data: bytes):
        if self.connection and self.is_connected:
            try:
                await self.connection.send(data)
            except:
                pass

    async def stop(self):
        self.is_connected = False
        if self.connection:
            try:
                await self.connection.finish()
            except:
                pass

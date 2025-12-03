import warnings
# SUPPRESS WARNINGS
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

import os
import json
import asyncio
import re
import datetime
import base64
import audioop
from typing import AsyncGenerator
from dotenv import load_dotenv

from deepgram import DeepgramClient, DeepgramClientOptions, LiveOptions, LiveTranscriptionEvents
from groq import AsyncGroq
import httpx
from fpdf import FPDF
try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None

load_dotenv()

# --- UTILS ---
class LocationStore:
    _location = "Unknown Location"
    @classmethod
    def update(cls, coords):
        if coords and "," in coords:
            cls._location = coords.strip()
            print(f">>> [GPS] Updated: {cls._location}")
    @classmethod
    def get(cls): return cls._location

# --- STATE MANAGER ---
class CalyxState:
    def __init__(self):
        self.mode = "DEFAULT"
        self.voice_id = "en-US-natalie"
        self.style = "Conversational"
        self.rate = 0
        self.pitch = 0
        self.mode_changed = True 
        self.interrupted = False 
        self.is_phone_call = False
        self.incident_context = "User triggered SOS."

    def signal_interruption(self): self.interrupted = True
    def reset_interruption(self): self.interrupted = False
    def update_incident_context(self, text): self.incident_context = text 

    def _set_mode(self, mode, voice, style, rate, pitch):
        if self.mode != mode:
            self.mode = mode
            self.voice_id = voice
            self.style = style
            self.rate = rate
            self.pitch = pitch
            self.mode_changed = True
            print(f">>> [STATE] SWITCHED TO: {mode}")

    def set_stealth_mode(self): self._set_mode("STEALTH", "en-US-natalie", "Calm", -5, -15)
    def set_decoy_mode(self): self._set_mode("DECOY", "en-US-ken", "Promo", 5, -10)
    def set_pizza_mode(self): self._set_mode("PIZZA", "en-US-natalie", "Conversational", 5, 2)
    def set_calm_mode(self): self._set_mode("CALM", "en-US-natalie", "Calm", -10, -2)
    def reset_mode(self): self._set_mode("DEFAULT", "en-US-natalie", "Conversational", 0, 0)


# --- GUARDIAN RELAY ---
class GuardianRelay:
    def __init__(self):
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_PHONE_NUMBER")
        self.to_num = os.getenv("EMERGENCY_CONTACT_NUMBER")
        self.ngrok_domain = os.getenv("NGROK_DOMAIN") 
        self.client = TwilioClient(self.sid, self.token) if (self.sid and TwilioClient) else None

    async def trigger_emergency_protocol(self):
        location_data = LocationStore.get()
        print(f"[GUARDIAN RELAY] 🚨 ACTIVATED: Calling {self.to_num}")
        
        clean_loc = location_data.replace(" ", "")
        map_link = f"http://maps.google.com/?q={clean_loc}"
        msg_body = f"URGENT: SILENT SOS via Calyx.\nLocation: {map_link}"

        if self.client:
            try:
                self.client.messages.create(body=msg_body, from_=self.from_num, to=self.to_num)
                print(f"[GUARDIAN RELAY] ✅ SMS Sent")
                if self.ngrok_domain:
                    domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
                    twiml = f"<Response><Connect><Stream url=\"wss://{domain}/ws/twilio\" /></Connect></Response>"
                    self.client.calls.create(twiml=twiml, to=self.to_num, from_=self.from_num)
                    print(f"[GUARDIAN RELAY] ✅ Live Call Initiated")
            except Exception as e: print(f"[GUARDIAN RELAY] ⚠️ Twilio Error: {e}")
        else: print(f"[GUARDIAN RELAY] ⚠️ Simulation Mode.")

    async def send_evidence_link(self, filename):
        if not self.client or not self.ngrok_domain: return
        domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
        link = f"https://{domain}/static/{filename}"
        try:
            self.client.messages.create(body=f"CALYX REPORT: Transcript: {link}", from_=self.from_num, to=self.to_num)
            print(f"[GUARDIAN RELAY] ✅ Evidence Sent")
        except: pass


# --- TWILIO PHONE AUDIO ---
class TwilioPhoneService:
    def __init__(self, state: CalyxState):
        self.state = state
        self.stream_sid = None
    async def process_incoming_audio(self, payload):
        try: return audioop.ulaw2lin(base64.b64decode(payload), 2)
        except: return None
    def create_outgoing_audio_msg(self, raw_pcm_audio: bytes):
        try:
            if len(raw_pcm_audio) % 2 != 0: raw_pcm_audio = raw_pcm_audio[:-1]
            payload = base64.b64encode(audioop.lin2ulaw(raw_pcm_audio, 2)).decode("utf-8")
            return { "event": "media", "streamSid": self.stream_sid, "media": { "payload": payload } }
        except: return None


# --- AI BRAIN ---
class GroqService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key)
        self.state = state 
        
        self.system_prompt = """
        You are Calyx, an elite AI First Responder.
        
        PROTOCOL:
        1. AMBIGUOUS DANGER (e.g. "I feel unsafe"): 
           - Step 1: Give immediate advice.
           - Step 2: ASK: "Should I call your emergency contact?"
           - If you ask this, YOU MUST also output: [SIGNAL:TIMER]
           
        2. CONFIRMED DANGER ("Call them!", "Yes"):
           - Output [SIGNAL:CALL] immediately.
        
        SCENARIOS:
        [MODE:STEALTH] -> "Hide", "Intruder". "Keep your voice down."
        [MODE:DECOY] -> "Activate Brother". "Hey! I see you."
        [MODE:PIZZA] -> "Order pizza". "Calyx Pizza. GPS confirmed."
        [MODE:CALM] -> Medical/Panic.
           - Burn: "Run cool water over it. Do not use ice."
           - Bleeding: "Apply pressure."
           - Panic: "Breathe. In... 2... 3... Out."
        [MODE:DEFAULT] -> General. "I am here."
        
        Output [MODE:X] or [SIGNAL:X] on new lines.
        """

    def set_phone_persona(self):
        self.state.is_phone_call = True
        context = self.state.incident_context
        self.memory = [{"role": "system", "content": f"""
        You are Calyx, an AI Alert System calling an Emergency Contact.
        CONTEXT: User triggered SOS. Report: "{context}".
        INSTRUCTIONS:
        - You have ALREADY said Hello.
        - Answer questions based on the Report.
        - Urge them to call 112/Police.
        """}]

    async def get_streaming_response(self, user_input: str) -> AsyncGenerator[str, None]:
        try:
            if not self.state.is_phone_call:
                if not hasattr(self, 'memory') or not self.memory:
                    self.memory = [{"role": "system", "content": self.system_prompt}]
            
            context_input = user_input
            if self.state.is_phone_call:
                context_input = f"[CONTACT ASKS]: {user_input}"
            
            self.memory.append({"role": "user", "content": context_input})
            if len(self.memory) > 20: self.memory = [self.memory[0]] + self.memory[-19:]
            
            completion = await self.client.chat.completions.create(
                model="llama-3.1-8b-instant", messages=self.memory, stream=True, temperature=0.3, max_tokens=250
            )
            buffer = ""
            full_resp = ""
            async for chunk in completion:
                if self.state.interrupted: break 
                content = chunk.choices[0].delta.content
                if content:
                    buffer += content
                    full_resp += content
                    
                    # --- TAG HANDLING ---
                    if "]" in buffer:
                        tags = re.findall(r"\[([A-Z]+:[A-Z]+)\]", buffer)
                        for tag in tags:
                            if "SIGNAL:CALL" in tag: yield b"SIGNAL_CALL"
                            if "SIGNAL:TIMER" in tag: yield b"SIGNAL_TIMER"
                            if "MODE:" in tag:
                                mode = tag.split(":")[1]
                                if mode == "STEALTH": self.state.set_stealth_mode()
                                elif mode == "DECOY": self.state.set_decoy_mode()
                                elif mode == "PIZZA": self.state.set_pizza_mode()
                                elif mode == "CALM": self.state.set_calm_mode()
                                elif mode == "DEFAULT": self.state.reset_mode()
                        buffer = re.sub(r"\[[A-Z]+:[A-Z]+\]", "", buffer)
                    
                    if buffer and not "[" in buffer: yield buffer; buffer = ""
            
            if buffer and not "[" in buffer: yield buffer
            self.memory.append({"role": "assistant", "content": full_resp})
        except Exception: yield "System active."


class EvidenceVault:
    def generate_pdf(self, memory):
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="CALYX | CRITICAL INCIDENT REPORT", ln=1, align='C')
        pdf.ln(10)
        
        for msg in memory:
            role = msg['role'].upper()
            if role == "SYSTEM": continue
            
            # --- CLEANING ---
            content = msg['content']
            # Remove wrappers
            content = content.replace("[CONTACT ASKS]:", "").replace("[PHONE CALL]", "")
            # Remove Tags using Regex
            content = re.sub(r"\[[A-Z]+:[A-Z]+\]", "", content)
            
            if not content.strip(): continue
            
            content = content.encode('latin-1', 'replace').decode('latin-1')
            pdf.set_text_color(200, 0, 0) if role == "ASSISTANT" else pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(0, 10, txt=f"{role}: {content}")
            pdf.ln(2)
        
        filename = f"evidence_{int(datetime.datetime.now().timestamp())}.pdf"
        filepath = os.path.join("static", filename)
        pdf.output(filepath)
        return filename

class DeepgramService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("DEEPGRAM_API_KEY")
        self.state = state 
        self.client = DeepgramClient(self.api_key, DeepgramClientOptions(options={"keepalive": "true"}))
        self.connection = None

    async def start(self, on_transcript_callback, is_phone=False):
        self.connection = self.client.listen.asyncwebsocket.v("1")
        async def on_message(sender, result, **kwargs):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) > 0 and result.is_final:
                print(f"[{'Phone' if is_phone else 'User'}]: {sentence}")
                if not is_phone: self.state.signal_interruption() 
                await on_transcript_callback(sentence)
        self.connection.on(LiveTranscriptionEvents.Transcript, on_message)
        options = LiveOptions(model="nova-2-phonecall" if is_phone else "nova-2", language="en-US", encoding="linear16", sample_rate=8000 if is_phone else 16000, channels=1)
        return await self.connection.start(options)

    async def send_audio(self, audio_data: bytes):
        if self.connection: await self.connection.send(audio_data)
    async def stop(self):
        if self.connection: await self.connection.finish()

class MurfService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("MURF_API_KEY")
        self.url = "https://api.murf.ai/v1/speech/generate" 
        self.state = state

    async def stream_audio(self, text_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        buffer = ""
        delimiters = [".", "?", "!", ";", ":", ","]
        async for text_chunk in text_stream:
            if self.state.interrupted: break 
            
            # Pass Signals
            if isinstance(text_chunk, bytes): 
                yield text_chunk
                continue
                
            buffer += text_chunk
            if len(buffer) > 20 and any(buffer.strip().endswith(p) for p in delimiters):
                async for chunk in self._generate_audio(buffer): yield chunk
                buffer = ""
        if buffer.strip() and not self.state.interrupted:
            async for chunk in self._generate_audio(buffer): yield chunk

    async def _generate_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        clean = text.strip()
        if not clean or "mode:" in clean.lower() or "signal:" in clean.lower(): return 
        if len(clean) < 2 and clean.lower() not in ["no", "ok", "hi"]: return
        headers = {"api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"}
        payload = {
            "voiceId": self.state.voice_id, "style": self.state.style, "text": clean,
            "rate": self.state.rate, "pitch": self.state.pitch, "sampleRate": 24000, "format": "MP3", "channelType": "MONO"
        }
        print(f"[TTS] Generating ({self.state.mode}): {clean}")
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("audioFile"): yield (await client.get(data["audioFile"])).content
            except Exception as e: print(f"Murf Error: {e}")

    async def generate_phone_audio(self, text: str) -> AsyncGenerator[bytes, None]:
        clean = text.strip()
        if not clean: return
        headers = {"api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"}
        payload = {
            "voiceId": "en-US-natalie", "style": "Promo", "text": clean, "rate": 0, "pitch": 0, "sampleRate": 8000, "format": "WAV", "channelType": "MONO"
        }
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(self.url, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("audioFile"):
                        wav_bytes = (await client.get(data["audioFile"])).content
                        pcm_bytes = wav_bytes[44:] if len(wav_bytes) > 44 else wav_bytes
                        yield pcm_bytes
            except Exception as e: print(f"Murf Phone Error: {e}")
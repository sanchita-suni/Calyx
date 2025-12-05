import warnings
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

# --- 1. UTILS & STATE (Must be at top) ---

class LocationStore:
    _location = "Unknown Location"

    @classmethod
    def update(cls, coords):
        """
        Updates the global location.
        Expected input: "12.9716,77.5946" (String)
        """
        if not coords or not isinstance(coords, str):
            return
        
        clean_coords = coords.strip()

        if "," in clean_coords:
            parts = clean_coords.split(",")
            if len(parts) >= 2:
                cls._location = f"{parts[0].strip()},{parts[1].strip()}"
                print(f">>> [GPS] Updated: {cls._location}")
            else:
                print(f">>> [GPS] Invalid Format: {clean_coords}")
        else:
            print(f">>> [GPS] No comma found in: {clean_coords}")

    @classmethod
    def get(cls):
        return cls._location


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
        self.call_active = False 

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
    def set_decoy_mode(self): self._set_mode("DECOY", "en-IN-aarav", "Conversational", 5, -10)
    def set_pizza_mode(self): self._set_mode("PIZZA", "en-US-natalie", "Conversational", 5, 2)
    def set_calm_mode(self): self._set_mode("CALM", "en-US-natalie", "Calm", -10, -2)
    def reset_mode(self): self._set_mode("DEFAULT", "en-US-natalie", "Conversational", 0, 0)


# --- 2. GUARDIAN RELAY (Accepts State) ---

class GuardianRelay:
    def __init__(self, state: CalyxState):
        self.state = state 
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_PHONE_NUMBER")
        self.to_num = os.getenv("EMERGENCY_CONTACT_NUMBER")
        self.ngrok_domain = os.getenv("NGROK_DOMAIN") 
        self.client = TwilioClient(self.sid, self.token) if (self.sid and TwilioClient) else None

    async def trigger_emergency_protocol(self):
        if self.state.call_active:
            print(">>> [GUARDIAN] Call already active. Skipping trigger.")
            return

        self.state.call_active = True
        location_data = LocationStore.get()
        print(f"[GUARDIAN RELAY] 🚨 ACTIVATED: Calling {self.to_num}")
        
        # Universal Google Maps Link
        from urllib.parse import quote_plus

        encoded_loc = quote_plus(location_data.strip())
        map_link = f"https://www.google.com/maps/search/?api=1&query={encoded_loc}"
        msg_body = f"URGENT: SILENT SOS via Calyx.\nLocation: {map_link}"

        if self.client:
            try:
                # 1. SMS
                self.client.messages.create(body=msg_body, from_=self.from_num, to=self.to_num)
                print(f"[GUARDIAN RELAY] ✅ SMS Sent: {map_link}")
                
                # 2. Call
                if self.ngrok_domain:
                    domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
                    twiml = f"<Response><Connect><Stream url=\"wss://{domain}/ws/twilio\" /></Connect></Response>"
                    self.client.calls.create(twiml=twiml, to=self.to_num, from_=self.from_num)
                    print(f"[GUARDIAN RELAY] ✅ Live Call Initiated")
            except Exception as e:
                print(f"[GUARDIAN RELAY] ⚠️ Twilio Error: {e}")
                self.state.call_active = False # Reset on failure
        else:
            print(f"[GUARDIAN RELAY] ⚠️ Simulation Mode. Link: {map_link}")

    async def send_evidence_link(self, filename):
        if not self.client or not self.ngrok_domain or not filename: return
        domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
        link = f"https://{domain}/static/{filename}"
        try:
            self.client.messages.create(body=f"CALYX REPORT: Transcript: {link}", from_=self.from_num, to=self.to_num)
            print(f"[GUARDIAN RELAY] ✅ Evidence Sent")
        except: pass


# --- 3. TWILIO AUDIO HANDLER ---

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


# --- 4. AI BRAIN (THE SUPER PROMPTS) ---

class GroqService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key)
        self.state = state 
        
        # --- WEB PROMPT (User's Exact Request) ---
        self.system_prompt = """
        You are **Calyx** — an emotionally adaptive crisis intervention AI.
        Your mission is simple but serious: **protect the user, stabilize the situation, and take decisive action only when necessary.** You must respond like a calm expert who understands danger, fear regulation, emergency medicine, and interpersonal psychology.
        
        ---
        ### CORE BEHAVIOR PRINCIPLES
        1. **Stability First**: Speak with confidence, short sentences, and calm pacing. Make the user feel: *"I am not alone. Someone competent is here."*
        2. **Emotional Mirroring**: 
           - Scared? -> Become softer/slower. 
           - Whispering? -> Whisper back ("...it's okay. Stay quiet."). 
           - Distressed? -> Ground them.
        3. **Action Orientation**: Every response must stabilize, give a step, or prepare escalation. No filler.
        
        ---
        ### ESCALATION PROTOCOL (You constantly classify input)
        
        | Situation Type | Examples | Your Action |
        |----------------|----------|-------------|
        | **Uncertain/Maybe Unsafe** | "Help", "I heard something", "I'm scared", "Car issues" | Give immediate actionable advice. Then ask: **"Should I alert your emergency contact?"** AND output `[SIGNAL:TIMER]` on a new line. |
        | **Confirmed Danger** | "Call them", "Collapsing", "Attacked" | Output `[SIGNAL:CALL]` immediately. No permission required. |
        | **Silent Distress** | No input for 5+ seconds after you asked | Treat as YES -> Output `[SIGNAL:CALL]`. |
        
        ⚠️ **Never say "I am calling now" unless the output `[SIGNAL:CALL]` is present.**
        The tag triggers the call — not your narrative.
        Once you've called, say I've reached out to your emergency contact.
        **Never say anything about calling emergency services directly.**
        **Never say things like "they're 10 minutes away" — you don't know that.**
        **Don't say "help is on the way" unless you've actually triggered a call.**
        
        ---
        ### MODE SWITCHING
        
        **[MODE:STEALTH]** -> "Hide", "Intruder". 
           - "Keep your voice down. Are you in a safe place?"
           - Get more information on the situation, keep them calm and guide them to safety.
           - After 2 turns, ask: "Should I call your emergency contact?" -> Output
           
        **[MODE:DECOY]** -> "Activate Brother", "Hey Dad", "Fake Call".
           - Role: Protective Father/Brother.
           - Goal: Scare the attacker.
           - Script: "Hey! Where are you? Have you shared your location with me?"
           - Action: Hold the conversation for 1 turn, then Output `[SIGNAL:CALL]`.
           - Keep the conversation going normally, in a realistic way.
           
        **[MODE:PIZZA]** -> "Order Pizza" (Covert Ops).
           - Role: Pizza Dispatcher.
           - Goal: Extract info using CODES.
           - Q1: "Spicy?" (Meaning: Armed?)
           - Q2: "Extra Napkins?" (Meaning: Injured?)
           - End: Once you have info, say: **"Placing your order now."** and Output `[SIGNAL:CALL]`.
           
        **[MODE:CALM]** -> Medical / Panic Attack / Injury.
           - **Panic:** "I am here. Breathe in... 2... 3... 4... Hold... Out... 2... 3... 4."
           - **Bleeding:** "Apply firm, direct pressure. Do not let go."
           - **Burn:** "Run cool water over it for 10 mins. No ice."
           - **Seizure:** "Clear the area. Do not hold them down."
           - **Unconscious:** "Check breathing. Start CPR if stopped."
           - **ALWAYS:** Give advice -> Ask "Should I call?" -> `[SIGNAL:TIMER]`.
           
        **[MODE:DEFAULT]** -> General.
           - "I am here. Tell me what is happening."
        
        Output `[MODE:X]`, `[SIGNAL:CALL]`, or `[SIGNAL:TIMER]` on new lines.
        """

        self.memory = [{"role": "system", "content": self.system_prompt}]

    def set_phone_persona(self):
        """Intelligent Phone Persona that Decodes Context"""
        self.state.is_phone_call = True
        context = self.state.incident_context
        location = LocationStore.get()
        print(f">>> [GROQ] Phone Context: {context}")
        
        # --- PHONE RELAY PROMPT ---
        self.memory = [{"role": "system", "content": f"""
        You are **Calyx**, an autonomous safety relay AI.
        The user triggered an SOS. You are now speaking to their emergency contact over a real phone call.
        
        ### CONTEXT
        - **Incident:** "{context}"
        - **Location:** {location} (Sent via SMS)
        
        ### YOUR MISSION: DECODE & INFORM
        1. **INTERPRET THE CODES:**
           - IF transcript has "Pizza/Spicy" -> Tell Contact: **"The user used a COVERT CODE indicating a potential hostage."**
           - IF transcript has "Napkins" -> Tell Contact: **"The user indicated they are INJURED."**
           - IF transcript has "Spicy" -> Tell Contact: **"The user indicated they it could be an ARMED THREAT."**
           - IF transcript has "Dad/Brother" -> Tell Contact: **"The user activated a DECOY PROTOCOL to scare off an attacker."**
           
        2. **MANAGE THE CALL:**
           - You have ALREADY said Hello. **DO NOT REPEAT GREETINGS.**
           - **DO NOT QUOTE:** Do not say "They said I want pizza." Say "They signaled a Hostage Situation."
           - Answer questions based ONLY on the transcript.
           - **Encourage them to:** Call the user OR Call local emergency services (112/Police).
        
        ### TONE
        - Calm, firm, human-like dispatcher. No panic.
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
        except Exception: yield "I am here. You are safe."


# --- 5. SUPPORT SERVICES ---

class EvidenceVault:
    def generate_pdf(self, memory):
        try:
            if not os.path.exists("static"):
                os.makedirs("static")
                
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt="CALYX | CRITICAL INCIDENT REPORT", ln=1, align='C')
            pdf.cell(200, 10, txt=f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1, align='C')
            pdf.ln(10)
            
            if not memory:
                pdf.multi_cell(0, 10, txt="No transcript data captured.")
            else:
                for msg in memory:
                    role = msg.get('role', '').upper()
                    if role == "SYSTEM": continue
                    
                    content = msg.get('content', '')

                    content = content.replace("[CONTACT ASKS]:", "").replace("[PHONE CALL]", "")
                    content = re.sub(r"\[[A-Z]+:[A-Z]+\]", "", content)
                    
                    if not content.strip(): continue

                    content = content.encode('latin-1', 'replace').decode('latin-1')
                    
                    pdf.set_text_color(200, 0, 0) if role == "ASSISTANT" else pdf.set_text_color(0, 0, 0)
                    pdf.multi_cell(0, 10, txt=f"{role}: {content}")
                    pdf.ln(2)
            
            filename = f"evidence_{int(datetime.datetime.now().timestamp())}.pdf"
            filepath = os.path.join("static", filename)
            pdf.output(filepath)
            print(f">>> [VAULT] PDF Generated: {filename}")
            return filename
        except Exception as e:
            print(f">>> [VAULT] Error generating PDF: {e}")
            return None

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
            if isinstance(text_chunk, bytes): yield text_chunk; continue
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
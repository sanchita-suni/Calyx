import warnings
# SUPPRESS WARNINGS MUST BE FIRST
warnings.filterwarnings("ignore", category=DeprecationWarning) 
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import json
import os
# Now import the brain
from brain import DeepgramService, GroqService, MurfService, CalyxState, GuardianRelay, EvidenceVault, TwilioPhoneService, LocationStore

app = FastAPI()

# Mount Static for Evidence PDFs
if not os.path.exists("static"): os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Global State
calyx_state = CalyxState()
relay = GuardianRelay()
vault = EvidenceVault()

@app.get("/")
async def get():
    with open("index.html", "r") as f:
        return HTMLResponse(content=f.read())

@app.get("/download/{filename}")
async def download_file(filename: str):
    return FileResponse(os.path.join("static", filename), filename=filename)

@app.on_event("startup")
async def startup_event():
    """Generates the WAV File for the Phone Call"""
    print(">>> [INIT] Checking Emergency Audio...")
    temp_state = CalyxState()
    temp_state.voice_id = "en-US-natalie"
    temp_state.style = "Promo"
    service = MurfService(temp_state)
    
    text = "This is a Calyx Emergency Alert. Your contact has triggered a Silent S O S. I have sent their location to your SMS. Please check it immediately."
    
    try:
        if not os.path.exists("emergency.wav"):
            print(">>> [INIT] Generating emergency.wav...")
            async for audio_bytes in service.generate_phone_audio(text):
                with open("emergency.wav", "wb") as f:
                    f.write(audio_bytes)
            print(">>> [INIT] Done.")
    except Exception as e:
        print(f">>> [INIT] Audio Generation skipped: {e}")

@app.get("/emergency.wav")
async def get_audio():
    if os.path.exists("emergency.wav"):
        return FileResponse("emergency.wav", media_type="audio/wav")
    return {"error": "File not found"}

# --- WEB UI ---
@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    dg_service = DeepgramService(calyx_state) 
    groq_service = GroqService(calyx_state) 
    tts_service = MurfService(calyx_state)
    transcript_queue = asyncio.Queue()
    sos_task = None
    websocket_open = True

    async def trigger_call():
        print(">>> [MAIN] Triggering Call...")
        # Capture context for the phone call
        context_str = " ".join([m['content'] for m in groq_service.memory[-4:] if m['role'] == 'user'])
        calyx_state.update_incident_context(context_str)
        
        await relay.trigger_emergency_protocol()
        if websocket_open: await websocket.send_text("ALERT_SENT")

    async def start_sos_countdown():
        try:
            print(">>> [TIMER] 5s Timer Started")
            await asyncio.sleep(5)
            await trigger_call()
        except asyncio.CancelledError: pass

    async def on_transcript(text):
        if sos_task and not sos_task.done(): sos_task.cancel()
        
        # Detect "Safe" or "Stop" to generate report
        if "safe" in text.lower() or "stop" in text.lower():
            pdf_file = vault.generate_pdf(groq_service.memory)
            await relay.send_evidence_link(pdf_file)
            if websocket_open: await websocket.send_text(f"DOWNLOAD:{pdf_file}")
            
        await transcript_queue.put(text)

    try:
        if not await dg_service.start(on_transcript, is_phone=False):
            await websocket.close()
            return

        async def receive_socket_commands():
            try:
                while websocket_open:
                    data = await websocket.receive()
                    if "bytes" in data: await dg_service.send_audio(data["bytes"])
                    if "text" in data:
                        cmd = data["text"]
                        if cmd.startswith("LOC:"): LocationStore.update(cmd.split("LOC:")[1])
                        
                        if cmd == "END_SESSION":
                            pdf_file = vault.generate_pdf(groq_service.memory)
                            await relay.send_evidence_link(pdf_file)
                            await websocket.send_text(f"DOWNLOAD:{pdf_file}")

                        if cmd == "TRIGGER_SOS":
                            nonlocal sos_task
                            calyx_state.update_incident_context("User tapped SOS Button.")
                            async def text_gen(): yield "Silent SOS. Calling in 5 seconds."
                            async for chunk in tts_service.stream_audio(text_gen()): 
                                if websocket_open: await websocket.send_bytes(chunk)
                            sos_task = asyncio.create_task(start_sos_countdown())
            except (WebSocketDisconnect, RuntimeError): pass

        async def process_conversation():
            nonlocal sos_task
            try:
                while websocket_open:
                    user_text = await transcript_queue.get()
                    calyx_state.reset_interruption()
                    if websocket_open: await websocket.send_text("CLEAR") 
                    
                    text_stream = groq_service.get_streaming_response(user_text)
                    audio_stream = tts_service.stream_audio(text_stream)
                    
                    if calyx_state.mode_changed and websocket_open:
                        await websocket.send_text(f"MODE:{calyx_state.mode}")
                        calyx_state.mode_changed = False
                        
                    async for chunk in audio_stream:
                        if calyx_state.interrupted: break
                        
                        # Handle Triggers
                        if chunk == b"SIGNAL_CALL": await trigger_call()
                        elif b"SIGNAL_TIMER" in chunk:
                             if sos_task: sos_task.cancel()
                             sos_task = asyncio.create_task(start_sos_countdown())
                        elif websocket_open: await websocket.send_bytes(chunk)
            except (WebSocketDisconnect, RuntimeError): pass

        await asyncio.wait([asyncio.create_task(receive_socket_commands()), asyncio.create_task(process_conversation())], return_when=asyncio.FIRST_COMPLETED)
    finally:
        websocket_open = False
        await dg_service.stop()

# --- TWILIO PHONE ---
@app.websocket("/ws/twilio")
async def twilio_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    phone_state = CalyxState()
    phone_state.incident_context = calyx_state.incident_context 
    phone_state.is_phone_call = True
    
    dg_service = DeepgramService(phone_state)
    twilio_service = TwilioPhoneService(phone_state)
    groq_service = GroqService(phone_state)
    groq_service.set_phone_persona()
    tts_service = MurfService(phone_state)

    async def on_phone_transcript(sentence):
        full_text = ""
        async for chunk in groq_service.get_streaming_response(sentence): full_text += chunk
        print(f"[Phone AI]: {full_text}")
        async for pcm in tts_service.generate_phone_audio(full_text):
            msg = twilio_service.create_outgoing_audio_msg(pcm)
            if msg: await websocket.send_json(msg)

    await dg_service.start(on_phone_transcript, is_phone=True)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg['event'] == 'start':
                twilio_service.stream_sid = msg['start']['streamSid']
                # Speak Intro
                intro = f"Hello. This is Calyx. An emergency has been triggered. The user reports: {phone_state.incident_context}. I sent their location to your SMS."
                async for chunk in tts_service.generate_phone_audio(intro):
                    await websocket.send_json(twilio_service.create_outgoing_audio_msg(chunk))
            elif msg['event'] == 'media':
                chunk = await twilio_service.process_incoming_audio(msg['media']['payload'])
                if chunk: await dg_service.send_audio(chunk)
    except Exception: pass
    finally: await dg_service.stop()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
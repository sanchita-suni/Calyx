import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import asyncio
import json
import os
from brain import DeepgramService, GroqService, MurfService, CalyxState, GuardianRelay, EvidenceVault, TwilioPhoneService, LocationStore

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
INDEX_PATH = os.path.join(BASE_DIR, "index.html")

if not os.path.exists(STATIC_DIR):
    os.makedirs(STATIC_DIR)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

calyx_state = CalyxState()
relay = GuardianRelay(calyx_state) 
vault = EvidenceVault()

@app.get("/")
async def get():
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="Error: index.html not found. Check backend folder.", status_code=500)

@app.get("/download/{filename}")
async def download_file(filename: str):
    file_location = os.path.join(STATIC_DIR, filename)
    if os.path.exists(file_location):
        return FileResponse(file_location, filename=filename)
    return {"error": "File not found"}

@app.on_event("startup")
async def startup_event():
    pass

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
        context_str = "User triggered Silent SOS."
        if hasattr(groq_service, 'memory'):
            recent = [m['content'] for m in groq_service.memory[-6:] if m['role'] == 'user']
            story = [msg for msg in recent if len(msg) > 4 and "call" not in msg.lower()]
            if story: context_str = ". ".join(story)
            
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
        if "safe" in text.lower() or "end session" in text.lower():
            pdf_file = vault.generate_pdf(groq_service.memory)
            await relay.send_evidence_link(pdf_file)
            if websocket_open: await websocket.send_text(f"DOWNLOAD:{pdf_file}")
        await transcript_queue.put(text)

    try:
        if not await dg_service.start(on_transcript, is_phone=False):
            await websocket.close()
            return

        async def receive_cmds():
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
                            sos_task = asyncio.create_task(start_sos_countdown())
            except (WebSocketDisconnect, RuntimeError): pass

        async def process_ai():
            nonlocal sos_task
            try:
                while websocket_open:
                    user_text = await transcript_queue.get()
                    calyx_state.reset_interruption()
                    if websocket_open: await websocket.send_text("CLEAR") 
                    
                    if "call" in user_text.lower() and "contact" in user_text.lower():
                         await trigger_call()

                    text_stream = groq_service.get_streaming_response(user_text)
                    audio_stream = tts_service.stream_audio(text_stream)
                    
                    if calyx_state.mode_changed and websocket_open:
                        await websocket.send_text(f"MODE:{calyx_state.mode}")
                        calyx_state.mode_changed = False
                        
                    async for chunk in audio_stream:
                        if calyx_state.interrupted: break
                        if chunk == b"SIGNAL_CALL": await trigger_call()
                        elif chunk == b"SIGNAL_TIMER":
                             if sos_task: sos_task.cancel()
                             sos_task = asyncio.create_task(start_sos_countdown())
                        elif websocket_open: await websocket.send_bytes(chunk)
            except (WebSocketDisconnect, RuntimeError): pass

        await asyncio.wait([asyncio.create_task(receive_cmds()), asyncio.create_task(process_ai())], return_when=asyncio.FIRST_COMPLETED)
    finally:
        websocket_open = False
        await dg_service.stop()

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
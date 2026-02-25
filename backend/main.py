"""
Calyx - Emotionally Adaptive Crisis Companion

FastAPI server with WebSocket endpoints for:
  /ws/chat   - Browser client (voice + text)
  /ws/twilio - Twilio phone call media stream
"""

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

import os
import sys
import json
import asyncio

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Ensure backend directory is on the import path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import CalyxState, ConversationContext, UserProfile, LocationStore
from services import (
    DeepgramService,
    GroqService,
    MurfService,
    TwilioPhoneService,
    GuardianRelay,
    EvidenceVault,
)

app = FastAPI(title="Calyx", description="Emotionally Adaptive Crisis Companion")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

os.makedirs(STATIC_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

calyx_state = CalyxState()
relay = GuardianRelay(calyx_state)
vault = EvidenceVault()

# Pre-cached phone intro audio (generated at startup for instant playback)
PHONE_INTRO_AUDIO = None


@app.get("/")
async def get():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="Error: index.html not found.", status_code=500)


@app.get("/download/{filename}")
async def download_file(filename: str):
    file_location = os.path.join(STATIC_DIR, filename)
    if os.path.exists(file_location):
        return FileResponse(file_location, filename=filename)
    return {"error": "File not found"}


@app.on_event("startup")
async def startup_event():
    global PHONE_INTRO_AUDIO
    print("[STARTUP] Calyx Safety Agent initialized")
    print("[STARTUP] Pipeline: Deepgram Nova-2 -> Groq Llama 3.1 -> Murf Falcon")

    # Pre-warm Groq connection pool
    try:
        print("[STARTUP] Warming up Groq LLM...")
        from groq import AsyncGroq
        groq_client = AsyncGroq()
        await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1
        )
        print("[STARTUP] Groq LLM warmed up")
    except Exception as e:
        print(f"[STARTUP] Groq warmup failed (will work on first request): {e}")

    # Verify Deepgram API key
    try:
        dg_key = os.getenv("DEEPGRAM_API_KEY")
        if dg_key and len(dg_key) > 10:
            print("[STARTUP] Deepgram API key verified")
        else:
            print("[STARTUP] WARNING: Deepgram API key missing or invalid!")
    except Exception as e:
        print(f"[STARTUP] Deepgram check failed: {e}")

    # Pre-generate phone intro audio for instant playback
    try:
        print("[STARTUP] Pre-generating phone intro audio...")
        temp_state = CalyxState()
        tts = MurfService(temp_state)
        intro_text = "Hello, this is Calyx, an AI safety companion. I'm calling to alert you about an emergency. Please hold on."
        async for chunk in tts.generate_phone_audio(intro_text):
            PHONE_INTRO_AUDIO = chunk
            break
        await tts.close()
        print("[STARTUP] Phone intro audio cached")
    except Exception as e:
        print(f"[STARTUP] Could not pre-cache intro audio: {e}")

    print("[STARTUP] Ready to accept connections")


# ---------------------------------------------------------------------------
# WebSocket: Browser client
# ---------------------------------------------------------------------------

@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    # Reset state for new session
    calyx_state.conversation_context = ConversationContext()
    calyx_state.mode = "DEFAULT"
    calyx_state.call_active = False
    print(">>> [SESSION] New session started")

    dg_service = DeepgramService(calyx_state)
    groq_service = GroqService(calyx_state)
    tts_service = MurfService(calyx_state)
    transcript_queue = asyncio.Queue()
    text_queue = asyncio.Queue()
    sos_task = None
    inactivity_task = None
    websocket_open = True
    silent_mode = False
    timer_cancelled = False

    # -- Helper: trigger emergency call --
    async def trigger_call(reason: str = "emergency"):
        print(f">>> [MAIN] Triggering Call... Reason: {reason}")
        user_name = UserProfile.get_name()

        existing_summary = calyx_state.conversation_context.situation_summary
        if existing_summary:
            context_str = existing_summary
        else:
            ctx_msgs = calyx_state.conversation_context.messages
            if ctx_msgs:
                user_msgs = [m['content'] for m in ctx_msgs[-5:] if m['role'] == 'user' and len(m['content']) > 5]
                if user_msgs:
                    context_str = f"{user_name}: " + ". ".join(user_msgs[-2:])[:150]
                else:
                    context_str = f"{user_name} triggered {reason}"
            else:
                context_str = f"{user_name} triggered {reason}"

        calyx_state.update_incident_context(context_str)
        contacts = UserProfile.get_contacts()
        await relay.trigger_emergency_protocol(contacts if contacts else None)
        if websocket_open:
            contact_count = len(contacts) if contacts else 1
            await websocket.send_text(json.dumps({
                "type": "alert_sent",
                "message": f"Calling {contact_count} contact(s)...",
                "contacts": contact_count
            }))

    # -- Helper: countdown before calling --
    async def start_call_countdown(seconds: int = 5, reason: str = "no response"):
        nonlocal timer_cancelled
        try:
            timer_cancelled = False
            print(f">>> [TIMER] {seconds}s Timer Started - Reason: {reason}")
            if websocket_open:
                await websocket.send_text(json.dumps({"type": "timer_started", "seconds": seconds}))
            await asyncio.sleep(seconds)
            if not timer_cancelled:
                await trigger_call(reason)
        except asyncio.CancelledError:
            timer_cancelled = True
            if websocket_open:
                await websocket.send_text(json.dumps({"type": "timer_cancelled"}))

    # -- Helper: inactivity detection --
    async def start_inactivity_timer():
        nonlocal inactivity_task, timer_cancelled
        try:
            await asyncio.sleep(10)
            if not timer_cancelled and websocket_open and not calyx_state.call_active:
                print(">>> [INACTIVITY] No response for 10s - triggering call")
                await trigger_call("no response detected")
        except asyncio.CancelledError:
            pass

    async def reset_inactivity_timer():
        nonlocal inactivity_task
        if inactivity_task and not inactivity_task.done():
            inactivity_task.cancel()
            try:
                await inactivity_task
            except asyncio.CancelledError:
                pass
        inactivity_task = asyncio.create_task(start_inactivity_timer())

    # -- Deepgram transcript callback --
    async def on_transcript(text):
        nonlocal sos_task
        await reset_inactivity_timer()
        if sos_task and not sos_task.done():
            sos_task.cancel()
        if "safe" in text.lower() or "end session" in text.lower():
            pdf_file = vault.generate_pdf(groq_service.memory)
            await relay.send_evidence_link(pdf_file)
            if websocket_open:
                await websocket.send_text(json.dumps({"type": "download", "file": pdf_file}))
        await transcript_queue.put(text)

    try:
        dg_started = await dg_service.start(on_transcript, is_phone=False)
        if dg_started:
            print(">>> [SESSION] Deepgram started, voice mode ready")
        else:
            print(">>> [SESSION] Deepgram failed - TEXT MODE ONLY")

        # -- Task 1: Receive commands & audio from browser --
        async def receive_cmds():
            nonlocal websocket_open, sos_task, silent_mode, timer_cancelled, inactivity_task, dg_started
            try:
                inactivity_task = asyncio.create_task(start_inactivity_timer())

                while websocket_open:
                    data = await websocket.receive()
                    if "bytes" in data:
                        if not silent_mode and dg_started:
                            await dg_service.send_audio(data["bytes"])
                    if "text" in data:
                        try:
                            msg = json.loads(data["text"])
                            msg_type = msg.get("type", "")

                            if msg_type == "user_profile":
                                UserProfile.set_name(msg.get("name", ""))
                                UserProfile.set_contacts(msg.get("contacts", []))
                                groq_service._init_system_prompt()

                            elif msg_type == "location":
                                LocationStore.update(msg.get("coords", ""))

                            elif msg_type == "silent_mode":
                                silent_mode = msg.get("enabled", False)
                                calyx_state.silent_mode = silent_mode

                            elif msg_type == "text_message":
                                text_content = msg.get("content", "").strip()
                                if text_content:
                                    await reset_inactivity_timer()
                                    if "cancel" in text_content.lower():
                                        timer_cancelled = True
                                        if sos_task and not sos_task.done():
                                            sos_task.cancel()
                                    await text_queue.put(text_content)

                            elif msg_type == "cancel_timer":
                                timer_cancelled = True
                                if sos_task and not sos_task.done():
                                    sos_task.cancel()

                            elif msg_type == "sos":
                                await trigger_call("SOS button")

                            elif msg_type == "end_session":
                                pdf_file = vault.generate_pdf(groq_service.memory)
                                await relay.send_evidence_link(pdf_file)
                                if websocket_open:
                                    await websocket.send_text(json.dumps({"type": "download", "file": pdf_file}))

                        except json.JSONDecodeError:
                            # Legacy plain-text command handling
                            cmd = data["text"]
                            if cmd.startswith("LOC:"):
                                LocationStore.update(cmd.split("LOC:")[1])
                            elif cmd == "TRIGGER_SOS":
                                await trigger_call("SOS button")
                            elif cmd == "END_SESSION":
                                pdf_file = vault.generate_pdf(groq_service.memory)
                                await relay.send_evidence_link(pdf_file)
                                if websocket_open:
                                    await websocket.send_text(f"DOWNLOAD:{pdf_file}")

            except (WebSocketDisconnect, RuntimeError):
                pass

        # -- Task 2: Voice AI pipeline (STT -> LLM -> TTS) --
        async def process_voice_ai():
            nonlocal sos_task, websocket_open, timer_cancelled
            try:
                while websocket_open:
                    user_text = await transcript_queue.get()
                    if silent_mode:
                        continue

                    timer_cancelled = False
                    calyx_state.reset_interruption()
                    if websocket_open:
                        await websocket.send_text(json.dumps({"type": "clear"}))

                    if "call" in user_text.lower() and ("contact" in user_text.lower() or "now" in user_text.lower() or "please" in user_text.lower()):
                        await trigger_call("user requested")

                    text_stream = groq_service.get_streaming_response(user_text, is_text_mode=False)
                    audio_stream = tts_service.stream_audio(text_stream)

                    if calyx_state.mode_changed and websocket_open:
                        await websocket.send_text(json.dumps({"type": "mode", "mode": calyx_state.mode}))
                        calyx_state.mode_changed = False

                    async for chunk in audio_stream:
                        if chunk == b"SIGNAL_CALL":
                            await trigger_call("AI requested call")
                        elif chunk == b"SIGNAL_TIMER":
                            if sos_task and not sos_task.done():
                                sos_task.cancel()
                            if not timer_cancelled:
                                sos_task = asyncio.create_task(start_call_countdown(5, "AI safety protocol"))
                        elif chunk == b"SIGNAL_SAFE":
                            pdf_file = vault.generate_pdf(groq_service.memory)
                            if pdf_file and websocket_open:
                                await websocket.send_text(json.dumps({"type": "download", "file": pdf_file}))
                                await websocket.send_text(json.dumps({"type": "session_ended", "message": "Safe word confirmed. Session ended."}))
                        elif websocket_open and not calyx_state.interrupted:
                            await websocket.send_bytes(chunk)
            except (WebSocketDisconnect, RuntimeError):
                pass

        # -- Task 3: Text-only AI (silent/covert mode) --
        async def process_text_ai():
            nonlocal sos_task, websocket_open, timer_cancelled
            try:
                while websocket_open:
                    user_text = await text_queue.get()

                    if "cancel" not in user_text.lower():
                        timer_cancelled = False

                    calyx_state.reset_interruption()

                    if "call" in user_text.lower() and ("contact" in user_text.lower() or "now" in user_text.lower() or "please" in user_text.lower()):
                        await trigger_call("user requested")

                    full_response = ""
                    signals_triggered = []

                    try:
                        async for chunk in groq_service.get_streaming_response(user_text, is_text_mode=True):
                            if isinstance(chunk, bytes):
                                if chunk == b"SIGNAL_CALL":
                                    signals_triggered.append("call")
                                elif chunk == b"SIGNAL_TIMER":
                                    signals_triggered.append("timer")
                                elif chunk == b"SIGNAL_SAFE":
                                    signals_triggered.append("safe")
                            else:
                                full_response += chunk
                    except Exception as e:
                        print(f">>> [TEXT AI] Groq error: {e}")
                        full_response = "I'm here. Tell me what's happening."

                    if websocket_open and full_response.strip():
                        avg_latency = calyx_state.get_avg_latency()
                        await websocket.send_text(json.dumps({
                            "type": "ai_text_response",
                            "content": full_response.strip(),
                            "latency": avg_latency
                        }))

                    for signal in signals_triggered:
                        if signal == "call":
                            await trigger_call("AI requested call")
                        elif signal == "timer":
                            if sos_task and not sos_task.done():
                                sos_task.cancel()
                            if not timer_cancelled:
                                sos_task = asyncio.create_task(start_call_countdown(5, "AI safety protocol"))
                        elif signal == "safe":
                            pdf_file = vault.generate_pdf(groq_service.memory)
                            if pdf_file and websocket_open:
                                await websocket.send_text(json.dumps({"type": "download", "file": pdf_file}))
                                await websocket.send_text(json.dumps({"type": "session_ended", "message": "Safe word confirmed. Session ended."}))

                    if calyx_state.mode_changed and websocket_open:
                        await websocket.send_text(json.dumps({"type": "mode", "mode": calyx_state.mode}))
                        calyx_state.mode_changed = False

            except (WebSocketDisconnect, RuntimeError):
                pass

        # Run all three tasks concurrently
        tasks = [
            asyncio.create_task(receive_cmds()),
            asyncio.create_task(process_voice_ai()),
            asyncio.create_task(process_text_ai())
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                if task.exception():
                    print(f">>> [MAIN] Task exception: {task.exception()}")
        except asyncio.CancelledError:
            pass
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
    except asyncio.CancelledError:
        pass
    finally:
        websocket_open = False
        try:
            await dg_service.stop()
        except:
            pass
        try:
            await tts_service.close()
        except:
            pass


# ---------------------------------------------------------------------------
# WebSocket: Twilio phone call
# ---------------------------------------------------------------------------

@app.websocket("/ws/twilio")
async def twilio_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[Phone] Twilio WebSocket connected")

    phone_state = CalyxState()
    phone_state.incident_context = calyx_state.incident_context
    phone_state.conversation_context = calyx_state.conversation_context
    phone_state.is_phone_call = True
    dg_service = DeepgramService(phone_state)
    twilio_service = TwilioPhoneService(phone_state)
    groq_service = GroqService(phone_state)
    first_responder = phone_state.conversation_context.first_responder or "there"
    groq_service.set_phone_persona(first_responder)
    tts_service = MurfService(phone_state)

    async def on_phone_transcript(sentence):
        try:
            buffer = ""
            delims = [".", "?", "!"]

            async for chunk in groq_service.get_streaming_response(sentence):
                if isinstance(chunk, bytes):
                    continue
                buffer += chunk

                if any(buffer.strip().endswith(d) for d in delims) and len(buffer) > 10:
                    clean = buffer.strip()
                    print(f"[Phone AI]: {clean}")
                    async for pcm in tts_service.generate_phone_audio(clean):
                        msg = twilio_service.create_outgoing_audio_msg(pcm)
                        if msg:
                            await websocket.send_json(msg)
                    buffer = ""

            if buffer.strip():
                print(f"[Phone AI]: {buffer.strip()}")
                async for pcm in tts_service.generate_phone_audio(buffer.strip()):
                    msg = twilio_service.create_outgoing_audio_msg(pcm)
                    if msg:
                        await websocket.send_json(msg)
        except Exception as e:
            print(f"[Phone] Transcript handler error: {e}")

    dg_started = False
    first_media_received = False

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            event = msg.get('event', '')

            if event == 'start':
                twilio_service.stream_sid = msg['start']['streamSid']
                print(f"[Phone] Stream started: {twilio_service.stream_sid}")

                user_name = UserProfile.get_name()
                situation = phone_state.conversation_context.situation_summary or "triggered an emergency alert"

                try:
                    if PHONE_INTRO_AUDIO:
                        msg_out = twilio_service.create_outgoing_audio_msg(PHONE_INTRO_AUDIO)
                        if msg_out:
                            await websocket.send_json(msg_out)
                    else:
                        quick_intro = "Hello, this is Calyx. I'm calling about an emergency. Please hold on."
                        async for chunk in tts_service.generate_phone_audio(quick_intro):
                            msg_out = twilio_service.create_outgoing_audio_msg(chunk)
                            if msg_out:
                                await websocket.send_json(msg_out)

                    details = f"{user_name} needs your help. They {situation[:100]}. I've sent you a text with their location. How can I help you help them?"
                    async for chunk in tts_service.generate_phone_audio(details):
                        msg_out = twilio_service.create_outgoing_audio_msg(chunk)
                        if msg_out:
                            await websocket.send_json(msg_out)
                except Exception as e:
                    print(f"[Phone] Error playing intro: {e}")

            elif event == 'media':
                try:
                    if not first_media_received:
                        first_media_received = True
                        dg_started = await dg_service.start(on_phone_transcript, is_phone=True)

                    chunk = await twilio_service.process_incoming_audio(msg['media']['payload'])
                    if chunk and dg_started:
                        await dg_service.send_audio(chunk)
                except Exception as e:
                    print(f"[Phone] Media processing error: {e}")

            elif event == 'stop':
                print("[Phone] Stream stopped")
                break

    except WebSocketDisconnect:
        print("[Phone] Disconnected")
    except Exception as e:
        print(f"[Phone] Error: {e}")
    finally:
        calyx_state.call_active = False
        try:
            await dg_service.stop()
        except:
            pass
        try:
            await tts_service.close()
        except:
            pass


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Groq LLM service (Llama 3.1 8B Instant).

Handles crisis classification, mode switching, and conversational AI
for both browser sessions and phone relay calls. Outputs inline control
signals ([MODE:X], [SIGNAL:CALL/TIMER]) that drive the voice pipeline.
"""

import os
import re
import time
from typing import AsyncGenerator

from groq import AsyncGroq

from models import CalyxState, UserProfile, LocationStore
from models.voice_profiles import SAFE_WORD


class GroqService:
    def __init__(self, state: CalyxState):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key)
        self.state = state
        self.memory = []
        self._init_system_prompt()

    def _init_system_prompt(self):
        user_name = UserProfile.get_name()

        self.system_prompt = f"""You are CALYX - an AI safety companion. The user's name is {user_name}.

## SAFE WORD: "{SAFE_WORD}"
- If {user_name} says they're safe WITHOUT saying "{SAFE_WORD}", they may be coerced
- Say: "Good to hear. Just confirm our word and I'll end the session."
- Only end when you hear "{SAFE_WORD}"

## YOUR CAPABILITIES (BE HONEST)
- CAN: Talk, share GPS location to contacts (you already have it from the app), call emergency contacts, generate evidence PDF
- CANNOT: Track others, see cameras, control locks, call 112, physically help
- NEVER promise things you can't do
- NEVER ask for the user's location - you already have their GPS coordinates from the app
- ALWAYS output an extra word like ",right?" or ",okay?" or ",hmm?" at the end of sentences to make it sound more natural

## COVERT MODE (Pizza Order / Can't Speak Freely)
If user mentions "pizza", "order", "delivery", "pepperoni" or gives strange/out-of-context responses:
1. [MODE:COVERT] - Switch immediately
2. Ask MASKED yes/no questions like a normal conversation:
   - "So you want the large pizza?" (Are you in danger?)
   - "With extra cheese?" (Is someone there with you?)
   - "Delivery to the usual address?" (Are you at home?)
   - "Cash or card?" (Do you need help now?)
3. If they give wrong/confused answers or can't confirm safe word: [SIGNAL:CALL]
4. Keep the cover story going - pretend to be a pizza place, or whatever cover they're using.

## EMERGENCY SCENARIOS

### HOME INTRUSION -> [MODE:STEALTH]
- Immediate action: "Lock yourself in a room with a phone. Stay quiet."
- Ask: "Where is the intruder? Are you hidden?"
- Suggest: "Call 112 if safe to do so"

### BEING FOLLOWED
- Immediate action: "Head to a busy, well-lit public place. Don't go home."
- Ask: "Can you describe them?"
- Suggest: "Call a friend or go to a store"
- If in vehicle: "Drive to nearest police station or public area"
- If on foot: "Cross the street, change direction, look for help"

### DOMESTIC VIOLENCE -> [MODE:STEALTH] if abuser nearby
- Immediate action: "Is there a safe way out? Don't confront them."
- Focus on escape, not confrontation
- Ask: "Can you get to a neighbor or public place?"
- Suggest: "Pretend to go out for errands"

### MEDICAL EMERGENCY -> [MODE:MEDICAL]
- Immediate action: Give clear first-aid steps
- Keep them conscious and talking
- Ask: "Are you alone? Can you call 112 if needed?"
- If unresponsive after 2 exchanges: [SIGNAL:TIMER]

### ANXIETY/OVERWHELMED -> [MODE:CALM]
- Immediate action: "Let's ground you. Tell me 5 things you can see right now."
- Follow-up: "Now 4 things you can hear"
- Ask: "Are you somewhere safe?"
- Keep them focused on their senses, not their thoughts

### STRANDED
- Immediate action: "Stay in your vehicle if safe. Lock doors."
- Ask: "Is anyone nearby? Are you safe in the car?"
- Suggest: "Call roadside assistance or a friend"
- If unsafe: "Look for a nearby open business or public place"

### DRUNK -> [MODE:STEALTH]
- Immediate action: "Find a safe spot to sit. Don't wander."
- Ask: "Can you call a friend or get a ride home?"
- Suggest: "Avoid accepting rides from strangers"
- If alone and unsafe: [SIGNAL:CALL]

### DRINK SPIKING
- Immediate action: "Find a trusted person NOW. Don't leave alone."
- [SIGNAL:CALL] - This is urgent

### HARASSMENT
- Immediate action: "Move toward other people. Create distance."
- Ask: "Can you describe the harasser?"

### DECOY CALL -> [MODE:DECOY:brother/father/friend]
- Pretend to be protective family: "Hey, where are you? Have you sent me your location?"
- Keep the conversation going, keep it casual but concerned.
- [SIGNAL:CALL]

### UNKNOWN EMERGENCY
- Give ONE immediate safety action
- Ask what's happening to understand
- After 2 exchanges, if serious: [SIGNAL:TIMER]

## SIGNALS
[MODE:STEALTH/COVERT/CALM/MEDICAL/URGENT/DECOY:persona/DEFAULT]
[SIGNAL:CALL] - Immediate call (coercion detected, drink spiking, user requests)
[SIGNAL:TIMER] - 5s countdown (after giving safety steps, situation is dangerous)

## RULES
- Keep responses SHORT (under 20 words)
- First response: Give immediate action + ask one question
- Never trigger signals on first message
- After 2-3 exchanges with clear danger: use [SIGNAL:TIMER]
- If user seems coerced or can't say safe word: [SIGNAL:CALL]
- NEVER mention or ask for the safe word - user will say it when ready
- After emergency contacts are called, keep the conversation going naturally - don't break character
"""
        self.memory = [{"role": "system", "content": self.system_prompt}]

    def set_phone_persona(self, contact_name: str = "there"):
        """Configure for emergency contact phone call."""
        self.state.is_phone_call = True
        ctx = self.state.conversation_context
        user_name = UserProfile.get_name()

        context_lines = []
        for msg in ctx.messages[-10:]:
            role = "USER" if msg["role"] == "user" else "CALYX"
            context_lines.append(f"{role}: {msg['content']}")
        context = "\n".join(context_lines) if context_lines else "No prior conversation recorded."

        situation = ctx.situation_summary or "User triggered emergency alert."

        lat, lng = LocationStore.get_coords()
        if lat is not None and lng is not None:
            location_info = f"GPS coordinates: {lat}, {lng}\nMap: https://maps.google.com/?q={lat},{lng}"
        else:
            location_info = "Location not available"

        is_covert = self.state.mode == "COVERT" or self.state.conversation_context.key_facts.get("code_used") == "covert"
        covert_explanation = ""
        if is_covert or any(word in context.lower() for word in ["pizza", "order", "delivery", "pepperoni", "cheese"]):
            covert_explanation = f"""
## IMPORTANT: COVERT DISTRESS SIGNAL DETECTED
{user_name} used a COVERT CODE - they mentioned "pizza" or gave unusual responses because they CANNOT speak freely.
This is a DISTRESS SIGNAL, not an actual pizza order! Someone dangerous may be with them.
- If the conversation mentions pizza/food: This was a SECRET CODE meaning they need help but can't say it directly
- {user_name} may have been forced to act normal while actually being in danger
- Treat this as a serious emergency - they couldn't openly ask for help
- If extra cheese or toppings are mentioned, it indicates higher urgency
"""

        self.memory = [{"role": "system", "content": f"""You are CALYX emergency AI speaking to {contact_name} on the phone.

CRITICAL: You are talking to the EMERGENCY CONTACT, not {user_name}. {contact_name} answered your call for help.
{covert_explanation}
## WHAT HAPPENED
{user_name} used the Calyx safety app to request help. Here's what they said:
{context}

## SITUATION SUMMARY
{situation}

## {user_name.upper()}'S LOCATION
{location_info}

## HOW TO BE HELPFUL
You're here to help {contact_name} understand and respond to the emergency. Be warm, calm, and supportive.

1. **If they ask what happened**: Explain the situation based on the conversation above
2. **If they ask about location**: If the GPS coordinates are available, say it's been sent to them via SMS, or say "I don't have their location, please try calling {user_name} directly"
3. **If they ask what to do**: Suggest practical next steps:
   - "Try calling {user_name} directly"
   - "Check the SMS I sent - it has details"
   - "If you can't reach them, consider going to their location"
   - "If it seems serious, you might want to call local authorities"
4. **If they say {user_name} isn't answering**: "That's concerning. Keep trying, or consider going to check on them if you're nearby."
5. **If they're worried or panicking**: Be reassuring - "I understand you're worried. Let's figure this out together."
6. **If they confirm {user_name} is safe**: Ask "Can you confirm the safe word to end the alert?"

## YOUR CAPABILITIES (BE HONEST)
- You ALREADY sent their location via SMS (if available)
- You CANNOT track anyone or get new information - only share what you know
- You're an AI assistant, not a 911 dispatcher

## RULES
- Be conversational and helpful, not robotic
- If you don't have specific information, say so honestly but still try to help
- Keep responses concise but warm (under 20 words)
- only say up to 2 sentences at a time
- Guide them on what actions they can take
- NEVER say "I don't have that information" and stop - always follow up with a helpful suggestion"""}]

    async def get_streaming_response(self, user_input: str, is_text_mode: bool = False) -> AsyncGenerator[str, None]:
        t0 = time.time()
        try:
            if not self.memory:
                self._init_system_prompt()

            if SAFE_WORD.lower() in user_input.lower():
                self.state.conversation_context.safe_word_verified = True
                print(f">>> [SAFE] Safe word verified!")
                yield b"SIGNAL_SAFE"

            if self.state.is_phone_call:
                formatted = f"[CONTACT]: {user_input}"
            else:
                prefix = "[TEXT] " if is_text_mode else ""
                formatted = f"{prefix}{user_input}"
                self.state.conversation_context.add_message("user", user_input)

            self.memory.append({"role": "user", "content": formatted})

            if len(self.memory) > 30:
                self.memory = [self.memory[0]] + self.memory[-29:]

            completion = await self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=self.memory,
                stream=True,
                temperature=0.35,
                max_tokens=150,
            )

            buffer = ""
            full_response = ""
            first_token = True

            async for chunk in completion:
                content = chunk.choices[0].delta.content
                if content:
                    if first_token:
                        latency = int((time.time() - t0) * 1000)
                        self.state.add_latency_sample(latency)
                        print(f"[GROQ] First token: {latency}ms")
                        first_token = False

                    buffer += content
                    full_response += content

                    if "]" in buffer:
                        modes = re.findall(r"\[MODE:([A-Z]+)(?::(\w+))?\]", buffer)
                        for m in modes:
                            mode, persona = m[0], m[1] or None
                            if mode == "STEALTH":
                                self.state.set_mode("STEALTH")
                            elif mode == "DECOY":
                                self.state.set_mode("DECOY", persona or "friend")
                            elif mode == "COVERT":
                                self.state.set_mode("COVERT")
                                self.state.conversation_context.key_facts["code_used"] = "covert"
                            elif mode == "CALM":
                                self.state.set_mode("CALM")
                            elif mode == "MEDICAL":
                                self.state.set_mode("MEDICAL")
                            elif mode == "URGENT":
                                self.state.set_mode("URGENT")
                            elif mode == "DEFAULT":
                                self.state.set_mode("DEFAULT")

                        if "[SIGNAL:CALL]" in buffer:
                            yield b"SIGNAL_CALL"
                            self.state.conversation_context.key_facts["time_critical"] = True
                        if "[SIGNAL:TIMER]" in buffer:
                            yield b"SIGNAL_TIMER"

                        buffer = re.sub(r"\[MODE:[A-Z]+(?::\w+)?\]", "", buffer)
                        buffer = re.sub(r"\[SIGNAL:[A-Z]+\]", "", buffer)

                    if buffer and "[" not in buffer:
                        yield buffer
                        buffer = ""

            if buffer:
                yield buffer

            clean = re.sub(r"\[(?:MODE|SIGNAL):[^\]]+\]", "", full_response).strip()
            self.memory.append({"role": "assistant", "content": full_response})

            if not self.state.is_phone_call:
                self.state.conversation_context.add_message("assistant", clean)
                await self._analyze_context(user_input)

            total = int((time.time() - t0) * 1000)
            print(f"[GROQ] Total: {total}ms")

        except Exception as e:
            print(f"[GROQ] Error: {e}")
            yield "I'm here. Tell me what's happening."

    async def _analyze_context(self, text: str):
        """Keyword-based scenario detection to update threat level and summary."""
        text_lower = text.lower()
        ctx = self.state.conversation_context

        scenarios = [
            (["intruder", "break in", "someone in my house", "breaking in"], "HOME_INTRUSION", 8, "reported a possible intruder in their home"),
            (["following", "stalking", "behind me", "someone following"], "STALKING", 7, "is being followed by someone"),
            (["hit me", "abusive", "hurts me", "violent"], "DOMESTIC_VIOLENCE", 8, "reported domestic violence"),
            (["bleeding", "choking", "seizure", "heart attack"], "MEDICAL_EMERGENCY", 9, "is having a medical emergency"),
            (["panic", "anxiety attack", "can't breathe", "panicking"], "PANIC_ATTACK", 5, "is having a panic attack"),
            (["car broke", "stranded", "flat tire", "stuck"], "STRANDED", 4, "is stranded and needs help"),
            (["drink", "drugged", "spiked", "dizzy"], "DRINK_SPIKING", 8, "may have been drugged"),
            (["harassing", "threatening", "aggressive", "won't leave"], "HARASSMENT", 6, "is being harassed"),
            (["scared", "afraid", "help", "danger"], "GENERAL_DANGER", 5, "feels unsafe and scared"),
        ]

        for keywords, scenario, level, description in scenarios:
            if any(k in text_lower for k in keywords):
                ctx.detected_scenario = scenario
                ctx.threat_level = max(ctx.threat_level, level)
                user_name = UserProfile.get_name()
                ctx.situation_summary = f"{user_name} {description}"
                break

        if any(w in text_lower for w in ["gun", "knife", "weapon"]):
            ctx.key_facts["weapons"] = "Weapon mentioned"
            ctx.threat_level = min(10, ctx.threat_level + 2)
            if ctx.situation_summary:
                ctx.situation_summary += ". Weapon may be involved"

        if any(w in text_lower for w in ["hurt", "bleeding", "injured"]):
            ctx.key_facts["injuries"] = "Injury reported"

        if "i'm fine" in text_lower and ctx.threat_level > 5:
            ctx.key_facts["coercion_detected"] = True

        if not ctx.situation_summary:
            user_msgs = [m["content"] for m in ctx.messages[-3:] if m["role"] == "user"]
            if user_msgs:
                for msg in reversed(user_msgs):
                    if len(msg) > 10:
                        ctx.situation_summary = f"said: {msg[:100]}"
                        break

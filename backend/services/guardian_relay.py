"""
Guardian Relay - Multi-contact emergency notification system.

Sends SMS with GPS location to all configured contacts and initiates
a live AI phone call to the primary contact via Twilio.
"""

import os
from typing import List, Dict

try:
    from twilio.rest import Client as TwilioClient
except ImportError:
    TwilioClient = None

from models import CalyxState, UserProfile, LocationStore


class GuardianRelay:
    def __init__(self, state: CalyxState):
        self.state = state
        self.sid = os.getenv("TWILIO_ACCOUNT_SID")
        self.token = os.getenv("TWILIO_AUTH_TOKEN")
        self.from_num = os.getenv("TWILIO_PHONE_NUMBER")
        self.ngrok_domain = os.getenv("NGROK_DOMAIN")
        self.client = TwilioClient(self.sid, self.token) if (self.sid and TwilioClient) else None
        self.first_responder_call_sid = None

    async def trigger_emergency_protocol(self, contacts: List[Dict] = None):
        if self.state.call_active:
            print(">>> [GUARDIAN] Call already active.")
            return

        self.state.call_active = True

        if not contacts:
            env_contact = os.getenv("EMERGENCY_CONTACT_NUMBER")
            if env_contact:
                contacts = [{"name": "Emergency Contact", "phone": env_contact}]
            else:
                contacts = []

        if not contacts:
            print(">>> [GUARDIAN] No contacts configured")
            return

        user_name = UserProfile.get_name()
        lat, lng = LocationStore.get_coords()

        print(f"[GUARDIAN] Emergency protocol: alerting {len(contacts)} contact(s)")

        sms_body = self.state.conversation_context.generate_sms_briefing(lat, lng)

        if self.client:
            try:
                for contact in contacts:
                    phone = contact.get("phone", "").strip()
                    name = contact.get("name", "Contact")
                    if phone:
                        personalized_sms = f"Hi {name},\n\n{sms_body}"
                        self.client.messages.create(
                            body=personalized_sms,
                            from_=self.from_num,
                            to=phone
                        )
                        print(f"[GUARDIAN] SMS sent to {name}: {phone}")

                if contacts and self.ngrok_domain:
                    first_contact = contacts[0]
                    phone = first_contact.get("phone", "").strip()
                    if phone:
                        domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
                        twiml = f'<Response><Connect><Stream url="wss://{domain}/ws/twilio" /></Connect></Response>'
                        call = self.client.calls.create(
                            twiml=twiml,
                            to=phone,
                            from_=self.from_num
                        )
                        self.first_responder_call_sid = call.sid
                        self.state.conversation_context.first_responder = first_contact.get("name")
                        print(f"[GUARDIAN] Calling {first_contact.get('name')}: {phone}")

                        for contact in contacts[1:]:
                            phone = contact.get("phone", "").strip()
                            name = contact.get("name", "")
                            if phone:
                                auto_msg = f"This is Calyx emergency system. {user_name} has triggered an emergency alert. Please check your SMS for details and location. Another contact is being connected to the AI system for more information."
                                auto_twiml = f'<Response><Say voice="alice">{auto_msg}</Say></Response>'
                                self.client.calls.create(
                                    twiml=auto_twiml,
                                    to=phone,
                                    from_=self.from_num
                                )
                                print(f"[GUARDIAN] Auto-call to {name}: {phone}")

            except Exception as e:
                print(f"[GUARDIAN] Error: {e}")
                self.state.call_active = False
        else:
            print(f"[GUARDIAN] Simulation mode - SMS: {sms_body[:100]}...")

    async def send_evidence_link(self, filename, contacts: List[Dict] = None):
        if not self.client or not self.ngrok_domain or not filename:
            return

        domain = self.ngrok_domain.replace("https://", "").replace("http://", "").strip("/")
        link = f"https://{domain}/static/{filename}"

        if not contacts:
            env_contact = os.getenv("EMERGENCY_CONTACT_NUMBER")
            if env_contact:
                contacts = [{"phone": env_contact}]

        for contact in (contacts or []):
            phone = contact.get("phone", "").strip()
            if phone:
                try:
                    self.client.messages.create(
                        body=f"CALYX INCIDENT REPORT: {link}",
                        from_=self.from_num,
                        to=phone
                    )
                except:
                    pass

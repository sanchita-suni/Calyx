"""
Evidence Vault - Generates timestamped PDF incident reports.

Creates a transcript of the conversation with user/AI messages,
GPS coordinates, and metadata for post-incident documentation.
"""

import os
import re
import datetime

from fpdf import FPDF

from models import UserProfile, LocationStore


class EvidenceVault:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
        self.static_dir = os.path.normpath(self.static_dir)
        os.makedirs(self.static_dir, exist_ok=True)

    def generate_pdf(self, memory, user_name: str = None):
        try:
            user_name = user_name or UserProfile.get_name()

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", "B", 16)
            pdf.cell(200, 10, "CALYX INCIDENT REPORT", ln=1, align='C')
            pdf.set_font("Arial", "", 11)
            pdf.cell(200, 7, f"User: {user_name}", ln=1, align='C')
            pdf.cell(200, 7, f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=1, align='C')

            lat, lng = LocationStore.get_coords()
            if lat is not None and lng is not None:
                pdf.cell(200, 7, f"Location: {lat}, {lng}", ln=1, align='C')
                pdf.cell(200, 7, f"Map: https://maps.google.com/maps?q={lat},{lng}", ln=1, align='C')
            pdf.ln(8)

            pdf.set_font("Arial", "B", 12)
            pdf.cell(200, 8, "TRANSCRIPT", ln=1)
            pdf.set_font("Arial", "", 10)

            for msg in memory or []:
                role = msg.get('role', '').upper()
                if role == "SYSTEM":
                    continue

                content = msg.get('content', '')
                content = re.sub(r"\[(?:MODE|SIGNAL|TEXT|CONTACT)[^\]]*\]", "", content).strip()
                if not content:
                    continue

                content = content.encode('latin-1', 'replace').decode('latin-1')

                pdf.set_text_color(0, 100, 0) if role == "ASSISTANT" else pdf.set_text_color(0, 0, 0)
                prefix = "CALYX: " if role == "ASSISTANT" else f"{user_name}: "
                pdf.multi_cell(0, 5, f"{prefix}{content}")
                pdf.ln(2)

            filename = f"evidence_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            filepath = os.path.join(self.static_dir, filename)
            pdf.output(filepath)
            print(f">>> [VAULT] Generated: {filepath}")
            return filename

        except Exception as e:
            print(f">>> [VAULT] Error generating PDF: {e}")
            return None

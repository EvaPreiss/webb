# fhir_client.py
"""
Leichter FHIR-Client mit Auto-MOCK:
- Wenn FHIR_BASE_URL (z. B. http://localhost:8080/fhir) gesetzt und 'requests' verfügbar,
  werden echte POST/GETs gemacht.
- Sonst arbeitet der Client im MOCK-Modus und liefert Fake-IDs zurück.
"""

import os
import uuid
from datetime import datetime, timedelta
import json

FHIR_BASE_URL = "https://hapi.fhir.org/baseR5/"
HEADERS = {"Content-Type": "application/fhir+json"}


def create_patient(first_name, last_name, email):
    # 1. FHIR-Ressource erstellen (Payload)
    patient_resource = {
        "resourceType": "Patient",
        "name": [{"family": last_name, "given": [first_name]}],
        "telecom": [{"system": "email", "value": email, "use": "home"}]
        # ... weitere Felder
    }

    # 2. POST-Anfrage an den FHIR-Server senden
    response = requests.post(
        f"{FHIR_BASE_URL}Patient",
        headers=HEADERS,
        data=json.dumps(patient_resource)
    )
    response.raise_for_status()  # Löst einen Fehler bei schlechtem Statuscode aus

    # 3. Die vom Server zugewiesene ID extrahieren
    # Die ID befindet sich im 'id'-Feld des zurückgegebenen FHIR-Objekts,
    # oder im Location-Header.
    return response.json().get('id')

USE_REAL = bool(FHIR_BASE_URL)

try:
    import requests  # optional
except Exception:
    requests = None
    USE_REAL = False


# In fhir_client.py

def create_fhir_appointment(
        patient_fhir_id: str,
        provider_fhir_id: str,
        start_time: datetime,
        end_time: datetime,
        notes: str
) -> str:
    """Erzeugt eine FHIR Appointment Ressource; liefert die FHIR ID zurück."""

    # ACHTUNG: Die Zeitzone muss korrekt formatiert sein, z.B. mit 'Z' für UTC oder '+01:00'
    # Abhängig davon, wie Sie datetime-Objekte handhaben (naive oder aware)
    start_iso = start_time.isoformat()
    end_iso = end_time.isoformat()

    body = {
        "resourceType": "Appointment",
        "status": "booked",  # Annahme: Direkt gebucht
        "description": f"Appointment with {provider_fhir_id}",
        "note": [{"text": notes}],  # Notizen im Note-Feld speichern
        "start": start_iso,
        "end": end_iso,
        "participant": [
            {
                "actor": {"reference": f"Patient/{patient_fhir_id}"},
                "status": "accepted",
                "required": True
            },
            {
                "actor": {"reference": f"Practitioner/{provider_fhir_id}"},
                "status": "accepted",
                "required": True
            }
        ]
    }

    if USE_REAL and requests:
        r = requests.post(f"{FHIR_BASE_URL}Appointment", json=body, timeout=10)
        r.raise_for_status()
        appt = r.json()
        # Hole die ID entweder aus dem ID-Feld oder dem Location-Header
        return appt.get("id") or r.headers.get("Location", "").split('/')[-1]

    # MOCK-Modus
    return _mock_id("appt")


def delete_fhir_appointment(fhir_appointment_id: str) -> None:
    """Löscht eine FHIR Appointment Ressource."""
    if USE_REAL and requests:
        r = requests.delete(f"{FHIR_BASE_URL}Appointment/{fhir_appointment_id}", timeout=10)
        # 404 ist OK, falls schon gelöscht
        if r.status_code != 404:
            r.raise_for_status()
    # Im MOCK-Modus keine Aktion nötig
    return
def _mock_id(prefix: str) -> str:
    return f"mock-{prefix}-{uuid.uuid4().hex[:10]}"


def create_schedule(practitioner_id: str) -> str:
    """Erzeugt Schedule, referenziert den Practitioner; liefert Schedule-ID zurück."""
    if USE_REAL and requests:
        body = {
            "resourceType": "Schedule",
            "actor": [{"reference": f"Practitioner/{practitioner_id}"}],
            "planningHorizon": None,  # optional
            "active": True,
        }
        r = requests.post(f"{FHIR_BASE_URL}Schedule", json=body, timeout=10)
        r.raise_for_status()
        sch = r.json()
        return sch.get("id") or sch.get("entry", [{}])[0].get("resource", {}).get("id")
    return _mock_id("schedule")


def create_slots(schedule_id: str, start_date: datetime | None = None,
                 days: int = 5, times: list[tuple[int, int]] | None = None) -> list[str]:
    """
    Legt für die nächsten 'days' Tage Slots zur angegebenen Uhrzeit an.
    times: Liste von (hour, minute), z.B. [(9,0),(14,0)]
    Rückgabe: Liste von Slot-IDs (real oder mock).
    """
    if times is None:
        times = [(9, 0), (14, 0)]
    if start_date is None:
        start_date = datetime.now()

    ids = []
    if USE_REAL and requests:
        for d in range(days):
            base = start_date + timedelta(days=d)
            for (h, m) in times:
                begin = base.replace(hour=h, minute=m, second=0, microsecond=0)
                end = begin + timedelta(minutes=30)
                body = {
                    "resourceType": "Slot",
                    "schedule": {"reference": f"Schedule/{schedule_id}"},
                    "status": "free",
                    "start": begin.strftime("%Y-%m-%dT%H:%M:%S%z") or begin.isoformat(),
                    "end": end.strftime("%Y-%m-%dT%H:%M:%S%z") or end.isoformat(),
                }
                r = requests.post(f"{FHIR_BASE_URL}Slot", json=body, timeout=10)
                r.raise_for_status()
                slot = r.json()
                sid = slot.get("id") or slot.get("entry", [{}])[0].get("resource", {}).get("id")
                ids.append(sid)
        return ids

    # MOCK
    for d in range(days):
        for _ in times:
            ids.append(_mock_id("slot"))
    return ids


def get_slots_by_schedule(schedule_id: str) -> list[dict]:
    """
    Holt Slots (einfaches Format). Im MOCK-Modus generieren wir 5 Tage x 2 Zeiten.
    Rückgabe: [{'label': '28.11 — 09:00', 'date': 'YYYY-MM-DD', 'time': 'HH:MM'}]
    """
    out = []
    if USE_REAL and requests:
        # Minimaler GET – Details je nach Server variieren
        params = {"schedule": f"Schedule/{schedule_id}", "_count": "50"}
        r = requests.get(f"{FHIR_BASE_URL}/Slot", params=params, timeout=10)
        r.raise_for_status()
        bundle = r.json()
        entries = bundle.get("entry", [])
        for e in entries:
            res = e.get("resource", {})
            if res.get("status") != "free":
                continue
            start = res.get("start")
            try:
                dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            except Exception:
                continue
            label = f"{dt.strftime('%d.%m')} — {dt.strftime('%H:%M')}"
            out.append({"label": label, "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M")})
        return out

    # MOCK: 5 Tage, 09:00 & 14:00
    base = datetime.now()
    for i in range(5):
        day = base + timedelta(days=i)
        for (h, m) in [(9, 0), (14, 0)]:
            dt = day.replace(hour=h, minute=m, second=0, microsecond=0)
            out.append({"label": f"{dt.strftime('%d.%m')} — {dt.strftime('%H:%M')}",
                        "date": dt.strftime("%Y-%m-%d"), "time": dt.strftime("%H:%M")})
    return out

# database_service.py
from database_layer.db_instance import db
from database_layer.user_entity import User, UserRoles
from database_layer.appointment_entity import Appointment
from datetime import datetime, timedelta
from random import randint
import os
import fhir_client as fhir


# damit man die datenbank reseten kann (mithilfe von AI generiert)
def init(app, reset=False, populate=True):
        print("Initializing SQLAlchemy instance")
        db.init_app(app)

        with app.app_context():
            if reset:
                print("!!! DROPPING ALL TABLES !!!")
                db.drop_all()

                print("!!! RECREATING ALL TABLES !!!")
                db.create_all()

                if populate:
                    sqlite_populate()
                return
            db.create_all()


# ----------------- Convenience-Queries -----------------

def fetch_user_by_email(email):
    return User.query.filter_by(email=email).first()

def fetch_user_by_id(uid: int) -> User | None:
    return User.query.get(uid)

# database_service.py

# ... (Convenience-Queries) ...

def fetch_appointments_by_email(email):
    user = fetch_user_by_email(email)
    if user and user.role == UserRoles.patient:
        # Korrektur: Sortieren nach Appointment.start
        return fetch_patients_appointments_by_id(user.id)
    elif user:
        # Korrektur: Sortieren nach Appointment.start
        return fetch_gda_appointments_by_id(user.id)

def fetch_patients_appointments_by_id(pid):
    # ✅ KORRIGIERT: Verwende Appointment.start
    return Appointment.query.filter_by(patient_id=pid).order_by(Appointment.start).all()

def fetch_gda_appointments_by_id(gid):
    # ✅ KORRIGIERT: Verwende Appointment.start
    return Appointment.query.filter_by(provider_id=gid).order_by(Appointment.start).all()

# ... (Rest des Codes bleibt gleich) ...




def create_appointment(patient_id: int, provider_id: int, start_time: datetime, end_time: datetime, user_notes: str):
    # 1) Lokale User holen (um FHIR-IDs zu bekommen)
    patient = fetch_user_by_id(patient_id)
    provider = fetch_user_by_id(provider_id)
    if not patient or not provider:
        raise ValueError("Patient or provider not found")

    patient_fhir_id = patient.fhir_patient_id
    provider_fhir_id = provider.fhir_practitioner_id

    # 2) Erstelle Appointment auf FHIR und erhalte FHIR-ID
    try:
        fhir_appt_id = fhir.create_fhir_appointment(
            patient_fhir_id,
            provider_fhir_id,
            start_time,
            end_time,
            user_notes
        )
    except Exception as e:
        # FHIR failed -> fallback: entweder raise oder continue with None
        print("FHIR appointment creation failed:", e)
        fhir_appt_id = None

    appt = Appointment(
        patient_id=patient_id,
        provider_id=provider_id,
        fhir_appointment_id=fhir_appt_id,
        start=start_time,
        end=end_time
    )

    db.session.add(appt)
    db.session.commit()
    return appt

def delete_appointment_local_and_fhir(appt: Appointment):
    if appt.fhir_appointment_id:
        try:
            fhir.delete_fhir_appointment(appt.fhir_appointment_id)
        except Exception as e:
            print("Warning: failed deleting FHIR appointment:", e)
            # optional: weiter löschen oder aborten
    db.session.delete(appt)
    db.session.commit()

def fetch_all_gdas():
    return User.query.filter_by(role=UserRoles.gda)

def fetch_all_patients():
    return User.query.filter_by(role=UserRoles.patient)

def generate_random_appointment_datetime():
    base = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    return base + timedelta(
        days=randint(-14, 14),
        hours=randint(0, 23),
        minutes=randint(0, 59)
    )


# ----------------- Initialbefüllung (lokal + FHIR) -----------------

def sqlite_populate():
    print("Populating database with staff and patients...")

    gdas_to_process = [
        User(email="alexander.owens@biomedical.org", role=UserRoles.gda,
             user_password="heartpass", fhir_practitioner_id="822316"),
        User(email="sophia.ingram@biomedical.org", role=UserRoles.gda,
             user_password="eyepass", fhir_practitioner_id="822317"),
        User(email="taylor.mckenzie@biomedical.org", role=UserRoles.gda,
             user_password="physiopass", fhir_practitioner_id="822318"),
        User(email="elisa.bennett@biomedical.org", role=UserRoles.gda,
             user_password="brainpass", fhir_practitioner_id="822319"), ]

    gdas = []  # Hier speichern wir die finalen User-Objekte

    # NEU: Iteriere direkt über die User-Objekte
    for user in gdas_to_process:

        # 🚀 1. FHIR Schedule und Slots erstellen
        try:
            # Verwende die Attribute des User-Objekts, NICHT die Schlüssel (['email'])
            schedule_id = fhir.create_schedule(user.fhir_practitioner_id)

            # Schedule ID lokal speichern
            user.fhir_schedule_id = schedule_id

            # Slots erstellen
            fhir.create_slots(
                schedule_id=schedule_id,
                days=7,
                times=[(9, 0), (10, 0), (14, 0)]
            )
            print(f"Created Schedule {schedule_id} and Slots for {user.email}")

        except Exception as e:
            print(f"Warning: Failed to create FHIR Schedule/Slots for {user.email}. ({e})")
            user.fhir_schedule_id = None

        gdas.append(user)  # Füge das aktualisierte Objekt zur Liste hinzu

    db.session.add_all(gdas)
    db.session.commit()

    patients = [
        # wurden mit postman auf den FHIR servrer gesendet und dann die id die ich zurück bekomme
        User(email="maria.schneider@example.com", role=UserRoles.patient,
             user_password="maria123", fhir_patient_id="822300"),

        User(email="felix.mueller@example.com", role=UserRoles.patient,
             user_password="felix123", fhir_patient_id="822301"),

        User(email="thomas.becker@example.com", role=UserRoles.patient,
             user_password="thomas123", fhir_patient_id="822302"),

        User(email="lisa.wagner@example.com", role=UserRoles.patient,
             user_password="lisa123", fhir_patient_id="822303"),

        User(email="max.bauer@example.com", role=UserRoles.patient,
             user_password="max123", fhir_patient_id="822304"),

        User(email="anna.richter@example.com", role=UserRoles.patient,
             user_password="anna123", fhir_patient_id="822306"),

        User(email="daniel.weber@example.com", role=UserRoles.patient,
             user_password="daniel123", fhir_patient_id="822307"),

        User(email="johannes.meier@example.com", role=UserRoles.patient,
             user_password="johannes123", fhir_patient_id="822308"),


    ]
    db.session.add_all(patients)
    db.session.commit()

    print("Local storage created & populated with sample data (incl. FHIR IDs if available).")

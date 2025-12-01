import requests

import fhir_client as fhir
from flask import Flask, render_template, request, redirect, url_for, abort, session, flash
from werkzeug.exceptions import HTTPException
from datetime import datetime
import os
from datetime import datetime, timedelta
from fhir_client import delete_fhir_appointment

# Services & DB-Modelle
import database_service as ds
from database_layer.db_instance import db
from database_layer.user_entity import User, UserRoles
from database_layer.appointment_entity import Appointment

# -----------------------------------
# App & DB-Setup
# -----------------------------------
BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "local_storage_dev.db")
DB_URI = f"sqlite:///{DB_PATH}"

app = Flask(__name__)
app.config["SQLITE_FILEPATH"] = DB_PATH
app.config["SQLALCHEMY_DATABASE_URI"] = DB_URI
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Session-Key (für Login-Status)
app.secret_key = "change-me-in-prod"

# DB initialisieren / Seed-Daten anlegen
ds.init(app)

FHIR_BASE_URL = "https://hapi.fhir.org/baseR5"  # dein FHIR-Server

def get_fhir_display_name(user):
    try:
        fhir_id = (
            user.fhir_patient_id if user.role == UserRoles.patient
            else user.fhir_practitioner_id
        )

        resource_type = "Patient" if user.role == UserRoles.patient else "Practitioner"
        url = f"{FHIR_BASE_URL}/{resource_type}/{fhir_id}"
        data = requests.get(url).json()

        name_obj = data.get("name", [{"text": "Unbekannt"}])[0]

        # bevorzugte Darstellung
        display = (
                name_obj.get("text")
                or " ".join(name_obj.get("given", [])) + " " + name_obj.get("family", "")
        )
        return display.strip()
    except:
        return "Unbekannt"


# Zugriff auf User-Seite nur mit Login
@app.before_request
def protect_user_pages():
    # bookings-Route absichern
    if request.endpoint == "bookings":
        if "user_email" not in session:
            return redirect(url_for("landing_page"))


# -----------------------------------
# Routes
# -----------------------------------
@app.route("/")
def landing_page():
    return render_template("index.html")


@app.route("/help")
def help_page():
    return render_template("help.html")

# das noch machen, dass man eine confirmation bekommt
@app.route("/confirmation")
def confirmation():
    return render_template("hello_world.html")


@app.route("/<username>", methods=["GET", "POST"])
def bookings(username):
  # nur für eigenen bereich zugelassen
        if session.get("user_email") != username:
            return redirect(url_for("landing_page"))

        user = ds.fetch_user_by_email(username)
        if not user:
            abort(401)

        # ... (Code zum Ermitteln des Namens bleibt gleich)
        display_name = get_fhir_display_name(user)
        first_name = display_name.split(" ", 1)[0]
        last_name = display_name.split(" ", 1)[-1]

        # --- GET ANFRAGE ---
  # --- GET ANFRAGE ---

        if request.method == "GET":
            appointments = ds.fetch_appointments_by_email(username)

            gda_list = ds.fetch_all_gdas().all()
            # 1. FHIR GDA Daten vorbereiten (muss schedule_id enthalten)
            fhir_gdas = [
                # Hole die fhir_schedule_id (muss in Ihrer User-Entität existieren)
                {"email": g.email,
                 "display_name": get_fhir_display_name(g),
                 "fhir_schedule_id": getattr(g, 'fhir_schedule_id', None)
                 }
                for g in gda_list
            ]
            fhir_patients = [
                {"email": p.email, "display_name": get_fhir_display_name(p)}
                for p in ds.fetch_all_patients().all()
            ]

            # 2. Slots für den ersten GDA abrufen (Standardansicht)
            available_slots = []
            first_gda_schedule_id = fhir_gdas[0]["fhir_schedule_id"] if fhir_gdas else None

            if first_gda_schedule_id:
                try:
                    # Aufruf der FHIR-Funktion, die die Slots zurückgibt
                    available_slots = fhir.get_slots_by_schedule(first_gda_schedule_id)
                except Exception as e:
                    print(f"Failed to fetch slots from FHIR: {e}")

            # 3. Slots an das Template übergeben
            return render_template(
                "booking.html",
                user=user,
                user_first_name=first_name,
                user_last_name=last_name,
                appointments=appointments,
                gdas=fhir_gdas,
                patients=fhir_patients,
                get_fhir_display_name=get_fhir_display_name,
                UserRoles=UserRoles,
                available_slots=available_slots  # ⬅️ Hinzugefügt
            )
  # --- POST ANFRAGE ---


        if request.method == "POST":
            date = request.form.get("date")
            start_time = request.form.get("start_time")
            end_time = request.form.get("end_time")

            if not date or not start_time or not end_time:
                flash("Bitte alle Felder ausfüllen.", "error")
                return redirect(url_for("bookings", username=session.get("user_email")))

            # Kombiniere Datum + Uhrzeit zu datetime-Objekten
            start_dt = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
            end_dt = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M")

            # Patient / Provider IDs ermitteln
            user = ds.fetch_user_by_email(username)
            if user.role == UserRoles.patient:
                patient_id = user.id
                provider_email = request.form.get("gda")
                provider = ds.fetch_user_by_email(provider_email)
                provider_id = provider.id
            else:
                provider_id = user.id
                patient_email = request.form.get("patient")
                patient = ds.fetch_user_by_email(patient_email)
                patient_id = patient.id

            # Termin in DB + FHIR erstellen
            try:
                ds.create_appointment(patient_id, provider_id, start_dt, end_dt, user_notes="")
                flash("Termin erfolgreich gebucht!", "success")
            except Exception as e:
                flash(f"Fehler beim Buchen des Termins: {e}", "error")
                print("Appointment creation failed:", e)

            return redirect(url_for("bookings", username=username))


@app.route("/new_user", methods=["POST"])
def add_user():
    try:
    #um die FHIR-Ressource zu befüllen. Sie werden NICHT lokal gespeichert.
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        password = request.form.get("password")

        if not all([first_name, last_name, email, password]):
            abort(400, description="Missing required fields")

        role = UserRoles.patient

        existing_user = ds.fetch_user_by_email(email)  # ds.fetch_user_by_email
        if existing_user:
            abort(400, description="User with this email already exists")


        # lokalen user erstellen - nur mit mail, role und password
        new_user = User(email=email, role=role, user_password=password)
        db.session.add(new_user)
        db.session.commit()

        # fhir patient wird erstellt
        fhir_id = fhir.create_patient(first_name=first_name, last_name=last_name, email=email)

        # FHIR ID im lokalen User-Objekt speichern
        new_user.fhir_patient_id = fhir_id
        db.session.commit()

        #direkt einloggen
        session["user_email"] = email
        session["user_role"] = role.name
        return redirect(url_for("bookings", username=email))

    except Exception as e:
        abort(500, description=f"Failed to create user: {str(e)}")


@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    user = ds.fetch_user_by_email(email)

    if user and user.password == password:
        session["user_email"] = email
        session["user_role"] = user.role.name
        return redirect(url_for("bookings", username=email))
    else:
        abort(401, description="Invalid login data!")


@app.route("/logout")
def logout():
    session.pop("user_email", None)
    session.pop("user_role", None)
    return redirect(url_for("landing_page"))


# Fehlerseiten
@app.errorhandler(HTTPException)
def handle_http_exception(e):
    return (
        render_template(
            "error.html",
            status_code=e.code,
            message=e.description or e.name,
            status_text=e.name,
        ),
        e.code,
    )


if __name__ == "__main__":
    print("USING DB:", DB_PATH)
    app.run(host="0.0.0.0", debug=True)

"""
Seeds demo doctors, patients, and a handful of sample appointments so the
app is ready to click around in immediately after setup.

Usage: python seed_demo_data.py

Safe to re-run: existing emails are skipped rather than duplicated.

Calendar: appointments are created through the same booking path the API
uses, so each one also gets a (mock, unless Google credentials are
configured) calendar event id -- see app/services/calendar_service.py.
"""
import json
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.database import Base, engine, SessionLocal
from app.models.models import User, Role, DoctorProfile, Appointment
from app.auth import hash_password
from app.services.booking_service import book_appointment
from app.services.calendar_service import create_event

Base.metadata.create_all(bind=engine)
db = SessionLocal()

DEMO_PASSWORD = "demo1234"

STANDARD_HOURS = {
    "mon": ["09:00", "17:00"],
    "tue": ["09:00", "17:00"],
    "wed": ["09:00", "17:00"],
    "thu": ["09:00", "17:00"],
    "fri": ["09:00", "15:00"],
}

DEMO_DOCTORS = [
    {
        "email": "dr.sharma@healthbook.com",
        "full_name": "Dr. Aisha Sharma",
        "specialisation": "Cardiology",
        "slot_duration_minutes": 30,
        "working_hours": STANDARD_HOURS,
    },
    {
        "email": "dr.patel@healthbook.com",
        "full_name": "Dr. Raj Patel",
        "specialisation": "Dermatology",
        "slot_duration_minutes": 20,
        "working_hours": STANDARD_HOURS,
    },
    {
        "email": "dr.chen@healthbook.com",
        "full_name": "Dr. Lin Chen",
        "specialisation": "Pediatrics",
        "slot_duration_minutes": 30,
        "working_hours": {
            "mon": ["10:00", "18:00"],
            "tue": ["10:00", "18:00"],
            "wed": ["10:00", "18:00"],
            "thu": ["10:00", "18:00"],
            "sat": ["09:00", "13:00"],
        },
    },
    {
        "email": "dr.khan@healthbook.com",
        "full_name": "Dr. Imran Khan",
        "specialisation": "General Physician",
        "slot_duration_minutes": 15,
        "working_hours": STANDARD_HOURS,
    },
]

DEMO_PATIENTS = [
    {"email": "patient1@example.com", "full_name": "Emily Johnson", "phone": "555-0101"},
    {"email": "patient2@example.com", "full_name": "Michael Lee", "phone": "555-0102"},
    {"email": "patient3@example.com", "full_name": "Sofia Garcia", "phone": "555-0103"},
    {"email": "patient4@example.com", "full_name": "David Kim", "phone": "555-0104"},
]


def get_or_create_user(email, full_name, role, phone=None):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return existing, False
    user = User(
        email=email,
        hashed_password=hash_password(DEMO_PASSWORD),
        full_name=full_name,
        role=role,
        phone=phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def next_weekday(base: datetime, weekday_key: str) -> datetime:
    """Returns the next date (from base, inclusive) matching mon/tue/.../sun."""
    weekday_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    target = weekday_map[weekday_key]
    days_ahead = (target - base.weekday()) % 7
    return base + timedelta(days=days_ahead)


print("=== Seeding demo doctors ===")
created_doctors = []
for d in DEMO_DOCTORS:
    user, was_created = get_or_create_user(d["email"], d["full_name"], Role.doctor)
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == user.id).first()
    if not profile:
        profile = DoctorProfile(
            user_id=user.id,
            specialisation=d["specialisation"],
            slot_duration_minutes=d["slot_duration_minutes"],
            working_hours=json.dumps(d["working_hours"]),
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    created_doctors.append((user, profile, d["working_hours"]))
    status = "created" if was_created else "already exists"
    print(f"  {d['full_name']} ({d['specialisation']}) — {status}")

print("\n=== Seeding demo patients ===")
created_patients = []
for p in DEMO_PATIENTS:
    user, was_created = get_or_create_user(p["email"], p["full_name"], Role.patient, p["phone"])
    created_patients.append(user)
    status = "created" if was_created else "already exists"
    print(f"  {p['full_name']} — {status}")

print("\n=== Seeding demo appointments (with mock calendar events) ===")
now = datetime.utcnow()
appt_specs = [
    (0, "mon", 1),  # (doctor index, weekday key offset base, days-ahead-of-that-weekday bump)
    (1, "tue", 0),
    (2, "wed", 0),
    (3, "thu", 0),
]

booked_count = 0
for i, (doc_idx, wd_key, _bump) in enumerate(appt_specs):
    doctor_user, profile, hours = created_doctors[doc_idx]
    patient = created_patients[i % len(created_patients)]

    if wd_key not in hours:
        continue
    start_str, _end_str = hours[wd_key]
    h, m = map(int, start_str.split(":"))

    target_date = next_weekday(now + timedelta(days=1), wd_key)
    slot_start = datetime(target_date.year, target_date.month, target_date.day, h, m) + timedelta(
        hours=1  # offset from opening time so it doesn't collide across reruns at 09:00 exactly
    )

    exists = (
        db.query(Appointment)
        .filter(Appointment.doctor_id == profile.id, Appointment.slot_start == slot_start)
        .first()
    )
    if exists:
        print(f"  Skipping (already booked): {doctor_user.full_name} @ {slot_start}")
        continue

    try:
        appt = book_appointment(db, patient.id, profile, slot_start)
    except Exception as e:
        print(f"  Could not book demo appointment for {doctor_user.full_name}: {e}")
        continue

    # Create mock (or real, if Google creds configured) calendar events for both sides.
    patient_event_id = create_event(
        patient.google_credentials_json,
        summary=f"Appointment with {doctor_user.full_name}",
        description=f"Specialisation: {profile.specialisation}",
        start=appt.slot_start,
        end=appt.slot_end,
    )
    doctor_event_id = create_event(
        doctor_user.google_credentials_json,
        summary=f"Appointment with {patient.full_name}",
        description=f"Patient: {patient.full_name}",
        start=appt.slot_start,
        end=appt.slot_end,
    )
    appt.patient_calendar_event_id = patient_event_id
    appt.doctor_calendar_event_id = doctor_event_id
    appt.symptoms_text = "Demo data — routine check-up."
    db.commit()

    booked_count += 1
    print(f"  Booked: {patient.full_name} with {doctor_user.full_name} @ {slot_start}  "
          f"[calendar event: {patient_event_id}]")

db.close()

print("\n=== Done ===")
print(f"Doctors seeded: {len(DEMO_DOCTORS)} | Patients seeded: {len(DEMO_PATIENTS)} | "
      f"Demo appointments booked this run: {booked_count}")
print(f"\nAll demo accounts use the password: {DEMO_PASSWORD}")
print("\nDemo doctor logins:")
for d in DEMO_DOCTORS:
    print(f"  {d['email']}  /  {DEMO_PASSWORD}   ({d['specialisation']})")
print("\nDemo patient logins:")
for p in DEMO_PATIENTS:
    print(f"  {p['email']}  /  {DEMO_PASSWORD}")

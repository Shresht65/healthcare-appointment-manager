import json
from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_role, get_current_user
from app.models.models import User, Role, DoctorProfile, Appointment, AppointmentStatus
from app.schemas.appointment_schemas import BookingRequest, SymptomSubmit, AppointmentOut
from app.schemas.doctor_schemas import DoctorOut
from app.services.booking_service import (
    get_available_slots, book_appointment, SlotUnavailableError, DoctorOnLeaveError,
)
from app.services.llm_service import generate_pre_visit_summary
from app.services.email_service import send_email
from app.services.calendar_service import create_event

router = APIRouter(prefix="/patient", tags=["patient"])


@router.get("/doctors", response_model=list[DoctorOut])
def search_doctors(
    specialisation: str | None = None,
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(Role.patient)),
):
    q = db.query(DoctorProfile)
    if specialisation:
        q = q.filter(DoctorProfile.specialisation.ilike(f"%{specialisation}%"))
    profiles = q.all()
    return [
        DoctorOut(
            id=p.id,
            full_name=p.user.full_name,
            specialisation=p.specialisation,
            slot_duration_minutes=p.slot_duration_minutes,
            working_hours=json.loads(p.working_hours),
        )
        for p in profiles
    ]


@router.get("/doctors/{doctor_id}/slots")
def view_slots(
    doctor_id: str,
    day: date = Query(..., description="Date to check availability for, YYYY-MM-DD"),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(Role.patient)),
):
    doctor = db.query(DoctorProfile).filter(DoctorProfile.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    day_dt = datetime.combine(day, datetime.min.time())
    slots = get_available_slots(db, doctor, day_dt)
    return {"doctor_id": doctor_id, "date": str(day), "available_slots": [s.isoformat() for s in slots]}


@router.post("/appointments/book", response_model=AppointmentOut)
def book(
    payload: BookingRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.patient)),
):
    doctor = db.query(DoctorProfile).filter(DoctorProfile.id == payload.doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    try:
        appt = book_appointment(db, user.id, doctor, payload.slot_start)
    except DoctorOnLeaveError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SlotUnavailableError as e:
        # This is the path hit when two patients race for the same slot --
        # the second one lands here with a clean, actionable error.
        raise HTTPException(status_code=409, detail=str(e))

    # Calendar events for both sides (mocked if Google not configured yet)
    appt.patient_calendar_event_id = create_event(
        user.google_credentials_json,
        summary=f"Appointment with Dr. {doctor.user.full_name}",
        description="Booked via Healthcare Appointment Manager",
        start=appt.slot_start,
        end=appt.slot_end,
    )
    appt.doctor_calendar_event_id = create_event(
        doctor.user.google_credentials_json,
        summary=f"Appointment with {user.full_name}",
        description="Booked via Healthcare Appointment Manager",
        start=appt.slot_start,
        end=appt.slot_end,
    )
    db.commit()
    db.refresh(appt)

    send_email(
        db,
        to_email=user.email,
        subject="Appointment confirmed",
        body=(
            f"Dear {user.full_name},\n\nYour appointment with Dr. {doctor.user.full_name} "
            f"is confirmed for {appt.slot_start.strftime('%Y-%m-%d %H:%M')}.\n\n"
            "Please fill in your symptoms before the visit so your doctor can prepare."
        ),
        related_appointment_id=appt.id,
    )
    send_email(
        db,
        to_email=doctor.user.email,
        subject="New appointment booked",
        body=(
            f"Dear Dr. {doctor.user.full_name},\n\nA new appointment has been booked by "
            f"{user.full_name} for {appt.slot_start.strftime('%Y-%m-%d %H:%M')}."
        ),
        related_appointment_id=appt.id,
    )

    return appt


@router.post("/appointments/{appointment_id}/symptoms", response_model=AppointmentOut)
def submit_symptoms(
    appointment_id: str,
    payload: SymptomSubmit,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.patient)),
):
    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.patient_id == user.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appt.status != AppointmentStatus.booked:
        raise HTTPException(status_code=400, detail="Appointment is not active")

    appt.symptoms_text = payload.symptoms_text
    summary = generate_pre_visit_summary(payload.symptoms_text)
    appt.pre_visit_summary_json = json.dumps(summary)
    appt.urgency_level = summary["urgency_level"]

    db.commit()
    db.refresh(appt)
    return appt


@router.get("/appointments", response_model=list[AppointmentOut])
def my_appointments(db: Session = Depends(get_db), user: User = Depends(require_role(Role.patient))):
    return db.query(Appointment).filter(Appointment.patient_id == user.id).order_by(Appointment.slot_start).all()

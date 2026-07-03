"""
Admin-only routes: create doctor profiles, manage working hours, mark leave days.

Marking a leave day triggers the "affected patients must be notified" flow:
we find any existing booked appointments on that date, cancel them, and
fire off email + calendar cleanup for each. See the leave endpoint below.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_role, hash_password
from app.models.models import User, Role, DoctorProfile, DoctorLeave, AppointmentStatus
from app.schemas.doctor_schemas import DoctorCreate, DoctorOut, LeaveCreate
from app.services.booking_service import find_affected_appointments
from app.services.email_service import send_email
from app.services.calendar_service import delete_event

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/doctors", response_model=DoctorOut)
def create_doctor(
    payload: DoctorCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.admin)),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=Role.doctor,
    )
    db.add(user)
    db.flush()  # get user.id without committing yet

    profile = DoctorProfile(
        user_id=user.id,
        specialisation=payload.specialisation,
        slot_duration_minutes=payload.slot_duration_minutes,
        working_hours=json.dumps(payload.working_hours),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return DoctorOut(
        id=profile.id,
        full_name=user.full_name,
        specialisation=profile.specialisation,
        slot_duration_minutes=profile.slot_duration_minutes,
        working_hours=payload.working_hours,
    )


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors(db: Session = Depends(get_db), _admin: User = Depends(require_role(Role.admin))):
    profiles = db.query(DoctorProfile).all()
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


@router.post("/doctors/{doctor_id}/leave")
def mark_leave(
    doctor_id: str,
    payload: LeaveCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.admin, Role.doctor)),
):
    doctor = db.query(DoctorProfile).filter(DoctorProfile.id == doctor_id).first()
    if not doctor:
        raise HTTPException(status_code=404, detail="Doctor not found")

    leave_dt = datetime.combine(payload.leave_date, datetime.min.time())

    leave = DoctorLeave(doctor_id=doctor_id, leave_date=leave_dt, reason=payload.reason)
    db.add(leave)
    db.commit()

    # Find and handle any existing bookings on this date.
    affected = find_affected_appointments(db, doctor_id, leave_dt)
    notified = []
    for appt in affected:
        appt.status = AppointmentStatus.cancelled
        db.commit()

        # Clean up calendar events for both sides
        if appt.patient_calendar_event_id:
            delete_event(appt.patient.google_credentials_json, appt.patient_calendar_event_id)
        if appt.doctor_calendar_event_id:
            delete_event(doctor.user.google_credentials_json, appt.doctor_calendar_event_id)

        send_email(
            db,
            to_email=appt.patient.email,
            subject="Your appointment has been cancelled",
            body=(
                f"Dear {appt.patient.full_name},\n\n"
                f"Unfortunately Dr. {doctor.user.full_name} is unavailable on "
                f"{appt.slot_start.strftime('%Y-%m-%d')} and your appointment at "
                f"{appt.slot_start.strftime('%H:%M')} has been cancelled. "
                "Please rebook at your convenience.\n\nWe apologise for the inconvenience."
            ),
            related_appointment_id=appt.id,
        )
        notified.append(appt.patient.email)

    return {
        "leave_id": leave.id,
        "affected_appointments_cancelled": len(affected),
        "patients_notified": notified,
    }

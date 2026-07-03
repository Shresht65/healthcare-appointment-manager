import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import require_role
from app.models.models import (
    User, Role, DoctorProfile, Appointment, AppointmentStatus, MedicationReminder,
)
from app.schemas.appointment_schemas import PostVisitSubmit, AppointmentOut
from app.services.llm_service import generate_post_visit_summary
from app.services.email_service import send_email

router = APIRouter(prefix="/doctor", tags=["doctor"])


def _get_own_profile(db: Session, user: User) -> DoctorProfile:
    profile = db.query(DoctorProfile).filter(DoctorProfile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Doctor profile not found")
    return profile


@router.get("/appointments", response_model=list[AppointmentOut])
def my_schedule(db: Session = Depends(get_db), user: User = Depends(require_role(Role.doctor))):
    profile = _get_own_profile(db, user)
    return (
        db.query(Appointment)
        .filter(Appointment.doctor_id == profile.id)
        .order_by(Appointment.slot_start)
        .all()
    )


@router.get("/appointments/{appointment_id}/pre-visit-summary")
def get_pre_visit_summary(
    appointment_id: str, db: Session = Depends(get_db), user: User = Depends(require_role(Role.doctor))
):
    profile = _get_own_profile(db, user)
    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.doctor_id == profile.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if not appt.pre_visit_summary_json:
        return {"available": False, "message": "Patient has not submitted symptoms yet."}
    return {"available": True, "summary": json.loads(appt.pre_visit_summary_json)}


@router.post("/appointments/{appointment_id}/post-visit", response_model=AppointmentOut)
def submit_post_visit(
    appointment_id: str,
    payload: PostVisitSubmit,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.doctor)),
):
    profile = _get_own_profile(db, user)
    appt = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id, Appointment.doctor_id == profile.id)
        .first()
    )
    if not appt:
        raise HTTPException(status_code=404, detail="Appointment not found")

    appt.clinical_notes = payload.clinical_notes
    prescription_list = [p.model_dump() for p in payload.prescription]
    appt.prescription_json = json.dumps(prescription_list)
    appt.status = AppointmentStatus.completed

    appt.post_visit_summary_text = generate_post_visit_summary(
        payload.clinical_notes, prescription_list
    )

    db.commit()
    db.refresh(appt)

    # Schedule medication reminders based on each drug's frequency_per_day.
    # Simple even-spacing across waking hours (8am-8pm) starting the day after visit.
    for item in prescription_list:
        freq = item["frequency_per_day"]
        duration = item["duration_days"]
        interval_hours = 12 / freq if freq > 0 else 24
        start_day = appt.slot_start.date() + timedelta(days=1)
        for day_offset in range(duration):
            for dose_num in range(freq):
                reminder_time = datetime.combine(
                    start_day + timedelta(days=day_offset), datetime.min.time()
                ) + timedelta(hours=8 + dose_num * interval_hours)
                db.add(
                    MedicationReminder(
                        appointment_id=appt.id,
                        patient_id=appt.patient_id,
                        drug_name=item["drug"],
                        scheduled_time=reminder_time,
                    )
                )
    db.commit()

    send_email(
        db,
        to_email=appt.patient.email,
        subject="Your visit summary is ready",
        body=appt.post_visit_summary_text,
        related_appointment_id=appt.id,
    )

    db.refresh(appt)
    return appt

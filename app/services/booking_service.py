"""
Booking logic. This is the part most likely to break under concurrency,
so the design here is deliberate:

1. AVAILABILITY CHECK (best-effort, fast): we compute open slots by taking
   the doctor's working hours, subtracting already-booked slots and leave
   days. This is just for displaying options to the user — it is NOT the
   source of truth for safety.

2. ACTUAL BOOKING (authoritative, safe under race conditions): when the
   patient confirms a slot, we attempt an INSERT inside a DB transaction.
   The `appointments` table has a UNIQUE constraint on (doctor_id, slot_start)
   (see models.py). If two patients click "book" on the same slot at the
   same time, only one INSERT succeeds — the second raises an
   IntegrityError, which we catch and turn into a clean "slot just got
   taken, please pick another" response. This works correctly even across
   multiple server processes/workers, because the guarantee is enforced by
   the database engine itself, not by in-memory locks.
"""
from datetime import datetime, timedelta, time
import json

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.models import Appointment, AppointmentStatus, DoctorProfile, DoctorLeave


class SlotUnavailableError(Exception):
    pass


class DoctorOnLeaveError(Exception):
    pass


def _parse_working_hours(doctor: DoctorProfile) -> dict:
    return json.loads(doctor.working_hours)


def _is_on_leave(db: Session, doctor_id: str, day: datetime) -> bool:
    day_start = datetime(day.year, day.month, day.day)
    day_end = day_start + timedelta(days=1)
    leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor_id,
            DoctorLeave.leave_date >= day_start,
            DoctorLeave.leave_date < day_end,
        )
        .first()
    )
    return leave is not None


def get_available_slots(db: Session, doctor: DoctorProfile, day: datetime) -> list[datetime]:
    """Returns list of available slot_start datetimes for a doctor on a given day."""
    if _is_on_leave(db, doctor.id, day):
        return []

    weekday_map = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    weekday_key = weekday_map[day.weekday()]
    hours = _parse_working_hours(doctor)

    if weekday_key not in hours:
        return []  # doctor doesn't work this day

    start_str, end_str = hours[weekday_key]
    h, m = map(int, start_str.split(":"))
    day_start = datetime(day.year, day.month, day.day, h, m)
    h, m = map(int, end_str.split(":"))
    day_end = datetime(day.year, day.month, day.day, h, m)

    slot_len = timedelta(minutes=doctor.slot_duration_minutes)

    # All possible slots in working hours
    all_slots = []
    cursor = day_start
    while cursor + slot_len <= day_end:
        all_slots.append(cursor)
        cursor += slot_len

    # Remove already-booked slots
    booked = (
        db.query(Appointment.slot_start)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.slot_start >= day_start,
            Appointment.slot_start < day_end,
        )
        .all()
    )
    booked_set = {b[0] for b in booked}

    # Don't offer slots in the past
    now = datetime.utcnow()

    return [s for s in all_slots if s not in booked_set and s > now]


def book_appointment(
    db: Session, patient_id: str, doctor: DoctorProfile, slot_start: datetime
) -> Appointment:
    """
    Authoritative booking attempt. Safe under concurrent requests because
    the DB UNIQUE constraint on (doctor_id, slot_start) is the real guard --
    see module docstring.
    """
    if _is_on_leave(db, doctor.id, slot_start):
        raise DoctorOnLeaveError("Doctor is on leave on this date.")

    slot_end = slot_start + timedelta(minutes=doctor.slot_duration_minutes)

    appointment = Appointment(
        patient_id=patient_id,
        doctor_id=doctor.id,
        slot_start=slot_start,
        slot_end=slot_end,
        status=AppointmentStatus.booked,
    )
    db.add(appointment)
    try:
        db.commit()
    except IntegrityError:
        # Another request booked this exact slot first -- the UNIQUE
        # constraint caught it. Roll back and surface a clean error.
        db.rollback()
        raise SlotUnavailableError(
            "This slot was just booked by someone else. Please choose another."
        )

    db.refresh(appointment)
    return appointment


def find_affected_appointments(db: Session, doctor_id: str, leave_date: datetime) -> list[Appointment]:
    """
    Used when admin/doctor marks a leave day. Returns all booked appointments
    on that date so they can be flagged for patient notification + cancellation.
    """
    day_start = datetime(leave_date.year, leave_date.month, leave_date.day)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.status == AppointmentStatus.booked,
            Appointment.slot_start >= day_start,
            Appointment.slot_start < day_end,
        )
        .all()
    )

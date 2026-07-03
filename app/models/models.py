"""
Database models.

Key design decision for double-booking prevention:
  `appointments` has a UNIQUE constraint on (doctor_id, slot_start).
  This means even if two requests race past the application-level
  availability check, the DATABASE itself will reject the second
  INSERT with an IntegrityError. The app layer catches that and
  returns a clean "slot no longer available" error instead of crashing.
  This is what makes concurrent booking attempts safe — see
  app/services/booking_service.py for the full flow.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, DateTime, Boolean, ForeignKey, Enum, Text,
    UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    patient = "patient"
    doctor = "doctor"
    admin = "admin"


class AppointmentStatus(str, enum.Enum):
    booked = "booked"
    cancelled = "cancelled"
    completed = "completed"


class UrgencyLevel(str, enum.Enum):
    low = "Low"
    medium = "Medium"
    high = "High"


class NotificationStatus(str, enum.Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class User(Base):
    """Base account table for patient/doctor/admin. Role-based auth pivots on `role`."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(Enum(Role), nullable=False)
    phone = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Stores Google OAuth2 token JSON (access + refresh token) once the user
    # connects their calendar. Null until they do. See calendar_service.py.
    google_credentials_json = Column(Text, nullable=True)

    doctor_profile = relationship("DoctorProfile", back_populates="user", uselist=False)


class DoctorProfile(Base):
    """Extra fields specific to doctors. Created/managed by admin."""
    __tablename__ = "doctor_profiles"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    specialisation = Column(String, nullable=False, index=True)
    slot_duration_minutes = Column(Integer, default=30)
    working_hours = Column(Text, nullable=False)
    # JSON string, e.g. {"mon": ["09:00","17:00"], "tue": ["09:00","17:00"], ...}

    user = relationship("User", back_populates="doctor_profile")
    leave_days = relationship("DoctorLeave", back_populates="doctor")


class DoctorLeave(Base):
    """A single date the doctor is unavailable. Checked when booking + used to find conflicts."""
    __tablename__ = "doctor_leave"

    id = Column(String, primary_key=True, default=gen_uuid)
    doctor_id = Column(String, ForeignKey("doctor_profiles.id"), nullable=False)
    leave_date = Column(DateTime, nullable=False)  # date-only, time component ignored
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    doctor = relationship("DoctorProfile", back_populates="leave_days")


class Appointment(Base):
    """
    Core booking record.

    UniqueConstraint(doctor_id, slot_start) is the safety net against
    double-booking under concurrent requests -- see module docstring.
    """
    __tablename__ = "appointments"
    __table_args__ = (
        UniqueConstraint("doctor_id", "slot_start", name="uq_doctor_slot"),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    doctor_id = Column(String, ForeignKey("doctor_profiles.id"), nullable=False)

    slot_start = Column(DateTime, nullable=False, index=True)
    slot_end = Column(DateTime, nullable=False)

    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.booked, nullable=False)

    # Pre-visit
    symptoms_text = Column(Text, nullable=True)
    pre_visit_summary_json = Column(Text, nullable=True)  # stores urgency, chief complaint, questions
    urgency_level = Column(Enum(UrgencyLevel), nullable=True)

    # Post-visit
    clinical_notes = Column(Text, nullable=True)
    prescription_json = Column(Text, nullable=True)  # list of {drug, dose, frequency, duration_days}
    post_visit_summary_text = Column(Text, nullable=True)

    # Calendar integration
    patient_calendar_event_id = Column(String, nullable=True)
    doctor_calendar_event_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = relationship("User", foreign_keys=[patient_id])
    doctor = relationship("DoctorProfile")


class MedicationReminder(Base):
    """One reminder occurrence derived from a prescription's frequency."""
    __tablename__ = "medication_reminders"

    id = Column(String, primary_key=True, default=gen_uuid)
    appointment_id = Column(String, ForeignKey("appointments.id"), nullable=False)
    patient_id = Column(String, ForeignKey("users.id"), nullable=False)
    drug_name = Column(String, nullable=False)
    scheduled_time = Column(DateTime, nullable=False, index=True)
    sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)


class NotificationLog(Base):
    """
    Tracks every email send attempt for retry purposes.
    Background job (app/services/scheduler.py) periodically retries
    anything still in `pending` or `failed` state under max_attempts.
    """
    __tablename__ = "notification_log"

    id = Column(String, primary_key=True, default=gen_uuid)
    recipient_email = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    related_appointment_id = Column(String, ForeignKey("appointments.id"), nullable=True)
    status = Column(Enum(NotificationStatus), default=NotificationStatus.pending)
    attempts = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

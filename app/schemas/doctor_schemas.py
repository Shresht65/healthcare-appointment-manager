from datetime import date
from typing import Optional
from pydantic import BaseModel, EmailStr


class DoctorCreate(BaseModel):
    """Admin uses this to create a doctor account + profile in one step."""
    email: EmailStr
    password: str
    full_name: str
    specialisation: str
    slot_duration_minutes: int = 30
    # JSON-able dict, e.g. {"mon": ["09:00","17:00"], "tue": ["09:00","17:00"]}
    working_hours: dict


class DoctorOut(BaseModel):
    id: str
    full_name: str
    specialisation: str
    slot_duration_minutes: int
    working_hours: dict

    class Config:
        from_attributes = True


class LeaveCreate(BaseModel):
    leave_date: date
    reason: Optional[str] = None

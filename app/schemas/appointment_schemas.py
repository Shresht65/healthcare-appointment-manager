from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BookingRequest(BaseModel):
    doctor_id: str
    slot_start: datetime  # must exactly match an available slot start


class SymptomSubmit(BaseModel):
    symptoms_text: str


class PrescriptionItem(BaseModel):
    drug: str
    dose: str
    frequency_per_day: int  # e.g. 3 = three times a day -> drives reminder scheduling
    duration_days: int


class PostVisitSubmit(BaseModel):
    clinical_notes: str
    prescription: List[PrescriptionItem] = []


class AppointmentOut(BaseModel):
    id: str
    doctor_id: str
    patient_id: str
    slot_start: datetime
    slot_end: datetime
    status: str
    urgency_level: Optional[str] = None
    pre_visit_summary_json: Optional[str] = None
    post_visit_summary_text: Optional[str] = None

    class Config:
        from_attributes = True

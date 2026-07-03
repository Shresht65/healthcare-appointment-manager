"""
Background jobs using APScheduler (no Redis/Celery needed -- runs in-process,
which keeps deployment to a single web service).

Two jobs:
  1. send_due_medication_reminders -- runs every minute, finds reminders
     whose scheduled_time has passed and sent=False, emails the patient,
     marks sent=True.
  2. retry_failed_notifications -- runs every 5 minutes, retries any
     notification stuck in 'failed' state (per email_service.py).
"""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from app.database import SessionLocal
from app.models.models import MedicationReminder
from app.services.email_service import send_email, retry_failed_notifications as _retry_notifications

logger = logging.getLogger(__name__)


def send_due_medication_reminders():
    db = SessionLocal()
    try:
        now = datetime.utcnow()
        due = (
            db.query(MedicationReminder)
            .filter(MedicationReminder.sent == False, MedicationReminder.scheduled_time <= now)  # noqa: E712
            .all()
        )
        for reminder in due:
            patient = reminder.appointment.patient if reminder.appointment else None
            if not patient:
                continue
            send_email(
                db,
                to_email=patient.email,
                subject="Medication reminder",
                body=f"Reminder: it's time to take your {reminder.drug_name}.",
                related_appointment_id=reminder.appointment_id,
            )
            reminder.sent = True
            reminder.sent_at = now
            db.commit()
        if due:
            logger.info(f"Sent {len(due)} medication reminders")
    except Exception as e:
        logger.error(f"Medication reminder job failed: {e}")
    finally:
        db.close()


def retry_failed_notifications_job():
    db = SessionLocal()
    try:
        count = _retry_notifications(db)
        if count:
            logger.info(f"Retried and sent {count} previously failed notifications")
    except Exception as e:
        logger.error(f"Notification retry job failed: {e}")
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler()
    scheduler.add_job(send_due_medication_reminders, "interval", minutes=1, id="med_reminders")
    scheduler.add_job(retry_failed_notifications_job, "interval", minutes=5, id="notification_retries")
    scheduler.start()
    logger.info("Background scheduler started (medication reminders + notification retries)")
    return scheduler

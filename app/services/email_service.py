"""
Email service. Every send attempt is logged to NotificationLog so the
background scheduler (app/services/scheduler.py) can retry anything that
failed, instead of silently dropping notifications.
"""
import logging
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import NotificationLog, NotificationStatus

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5


def _send_via_sendgrid(to_email: str, subject: str, body: str) -> bool:
    """Returns True on success, False on failure. Raises nothing -- caller logs."""
    if settings.EMAIL_MOCK_MODE:
        logger.info(f"[MOCK EMAIL] To: {to_email} | Subject: {subject}\n{body}")
        return True

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=settings.EMAIL_FROM,
            to_emails=to_email,
            subject=subject,
            plain_text_content=body,
        )
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        return 200 <= response.status_code < 300
    except Exception as e:
        logger.error(f"SendGrid send failed: {e}")
        return False


def send_email(
    db: Session,
    to_email: str,
    subject: str,
    body: str,
    related_appointment_id: str | None = None,
) -> NotificationLog:
    """
    Sends immediately and logs result. If it fails, the log entry stays
    in 'pending'/'failed' state so the background retry job can pick it up.
    """
    log = NotificationLog(
        recipient_email=to_email,
        subject=subject,
        body=body,
        related_appointment_id=related_appointment_id,
        status=NotificationStatus.pending,
        attempts=1,
    )
    db.add(log)
    db.commit()

    success = _send_via_sendgrid(to_email, subject, body)
    if success:
        log.status = NotificationStatus.sent
        from datetime import datetime
        log.sent_at = datetime.utcnow()
    else:
        log.status = NotificationStatus.failed
        log.last_error = "Send failed -- will retry via background job"

    db.commit()
    db.refresh(log)
    return log


def retry_failed_notifications(db: Session) -> int:
    """
    Called periodically by the scheduler. Retries any notification still
    under MAX_ATTEMPTS. Returns count of successfully sent retries.
    """
    from datetime import datetime

    failed = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.status == NotificationStatus.failed,
            NotificationLog.attempts < MAX_ATTEMPTS,
        )
        .all()
    )
    sent_count = 0
    for log in failed:
        log.attempts += 1
        success = _send_via_sendgrid(log.recipient_email, log.subject, log.body)
        if success:
            log.status = NotificationStatus.sent
            log.sent_at = datetime.utcnow()
            sent_count += 1
        else:
            log.last_error = f"Retry {log.attempts} failed"
        db.commit()
    return sent_count

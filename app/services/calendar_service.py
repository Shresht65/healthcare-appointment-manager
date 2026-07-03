"""
Google Calendar integration. Creates/updates/deletes events for both
patient and doctor on booking/reschedule/cancellation.

Auth model: each user (patient or doctor) connects their own Google account
once via OAuth2 (see app/routers/calendar_router.py for the auth flow).
Their refresh token is stored and used to create events on their calendar
without requiring re-login each time.

If Google credentials aren't configured (CALENDAR_MOCK_MODE), this returns
fake event IDs so the rest of the booking flow can be tested without a
real Google Cloud project set up yet.
"""
import logging
from datetime import datetime
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def get_calendar_service(credentials_json: str):
    """Builds an authenticated Google Calendar API client from stored OAuth2 credentials."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    import json as _json

    creds_data = _json.loads(credentials_json)
    creds = Credentials.from_authorized_user_info(creds_data)
    return build("calendar", "v3", credentials=creds)


def create_event(
    credentials_json: Optional[str],
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
) -> str:
    """Returns the created event's ID (real or mocked)."""
    if settings.CALENDAR_MOCK_MODE or not credentials_json:
        mock_id = f"mock-event-{start.isoformat()}"
        logger.info(f"[MOCK CALENDAR] Created event '{summary}' at {start} -> {mock_id}")
        return mock_id

    try:
        service = get_calendar_service(credentials_json)
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        return created["id"]
    except Exception as e:
        logger.error(f"Calendar event creation failed: {e}")
        return f"failed-{start.isoformat()}"


def update_event(
    credentials_json: Optional[str], event_id: str, start: datetime, end: datetime
) -> bool:
    if settings.CALENDAR_MOCK_MODE or not credentials_json or event_id.startswith(("mock-", "failed-")):
        logger.info(f"[MOCK CALENDAR] Updated event {event_id} -> {start}")
        return True

    try:
        service = get_calendar_service(credentials_json)
        event = service.events().get(calendarId="primary", eventId=event_id).execute()
        event["start"] = {"dateTime": start.isoformat(), "timeZone": "UTC"}
        event["end"] = {"dateTime": end.isoformat(), "timeZone": "UTC"}
        service.events().update(calendarId="primary", eventId=event_id, body=event).execute()
        return True
    except Exception as e:
        logger.error(f"Calendar event update failed: {e}")
        return False


def delete_event(credentials_json: Optional[str], event_id: str) -> bool:
    if settings.CALENDAR_MOCK_MODE or not credentials_json or event_id.startswith(("mock-", "failed-")):
        logger.info(f"[MOCK CALENDAR] Deleted event {event_id}")
        return True

    try:
        service = get_calendar_service(credentials_json)
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True
    except Exception as e:
        logger.error(f"Calendar event deletion failed: {e}")
        return False

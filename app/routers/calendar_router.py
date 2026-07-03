"""
Lets a logged-in user (patient or doctor) connect their Google Calendar.
Standard OAuth2 authorization-code flow. The resulting credentials JSON
is stored on the user record and used by calendar_service.py for all
future event create/update/delete calls.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.auth import get_current_user
from app.config import settings
from app.models.models import User

router = APIRouter(prefix="/calendar", tags=["calendar"])

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


@router.get("/connect")
def connect_calendar(user: User = Depends(get_current_user)):
    """Returns the Google OAuth consent URL the frontend should redirect to."""
    if settings.CALENDAR_MOCK_MODE:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar credentials not configured on the server yet "
            "(GOOGLE_CLIENT_ID/SECRET missing in .env). Running in mock mode.",
        )

    from google_auth_oauthlib.flow import Flow

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=user.id,  # carries the user id through the redirect
    )
    return {"auth_url": auth_url}


@router.get("/oauth2callback")
def oauth2_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    """Google redirects here after consent. `state` carries the user id."""
    from google_auth_oauthlib.flow import Flow

    user = db.query(User).filter(User.id == state).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials

    user.google_credentials_json = creds.to_json()
    db.commit()

    return RedirectResponse(url=f"{settings.APP_BASE_URL}/static/calendar_connected.html")

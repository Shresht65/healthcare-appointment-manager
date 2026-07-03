"""
Central configuration. All values are loaded from environment variables
(see .env.example). Nothing here should be hardcoded for production secrets.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")

    # --- Auth ---
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24h

    # --- LLM (Google Gemini) ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gemini-flash-latest")
    LLM_MOCK_MODE: bool = os.getenv("GEMINI_API_KEY", "") == ""

    # --- Email (SendGrid) ---
    SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "no-reply@example.com")
    EMAIL_MOCK_MODE: bool = os.getenv("SENDGRID_API_KEY", "") == ""

    # --- Google Calendar OAuth2 ---
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GOOGLE_REDIRECT_URI: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8000/calendar/oauth2callback"
    )
    CALENDAR_MOCK_MODE: bool = os.getenv("GOOGLE_CLIENT_ID", "") == ""

    # --- App ---
    APP_BASE_URL: str = os.getenv("APP_BASE_URL", "http://localhost:8000")
    SLOT_DURATION_DEFAULT_MIN: int = 30


settings = Settings()
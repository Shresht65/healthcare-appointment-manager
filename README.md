# Healthcare Appointment & Follow-up Manager

A full-stack healthcare platform with role-based access, AI symptom summaries, medication reminders, email notifications, and Google Calendar integration.

**Stack:** FastAPI · SQLAlchemy · SQLite/PostgreSQL · APScheduler · Anthropic API · SendGrid · Google Calendar API · Plain HTML/JS

---

## Quick Start (Local)

```bash
# 1. Clone / unzip the project
cd healthcare-appointment-manager

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy .env and fill in your keys
cp .env.example .env
# Edit .env — any key left blank runs that service in mock mode (see below)

# 5. Seed the admin account (first time only)
python seed_admin.py

# 6. Start the server
python run.py
# → Open http://localhost:8000
```

**Default admin credentials (change after first login):**
- Email: `admin@healthbook.com`
- Password: `admin123`

---

## Mock Modes (no API keys needed to develop)

Every external integration has a mock mode that activates automatically when the corresponding key is absent from `.env`:

| Service | Key needed | Mock behaviour |
|---|---|---|
| LLM (Claude) | `ANTHROPIC_API_KEY` | Returns a hardcoded-but-functional pre/post-visit summary |
| Email | `SENDGRID_API_KEY` | Prints the email to the server log instead of sending |
| Google Calendar | `GOOGLE_CLIENT_ID` | Returns fake event IDs; all calendar calls log to console |

This means you can run the full booking flow, symptom submission, post-visit notes, and reminders **without any API keys**.

---

## Environment Variables (`.env.example`)

```env
DATABASE_URL=sqlite:///./app.db          # or postgresql://user:pass@host/db
JWT_SECRET=change-me-to-long-random-string
JWT_EXPIRE_MINUTES=1440

ANTHROPIC_API_KEY=                       # leave blank = mock mode
LLM_MODEL=claude-sonnet-4-6

SENDGRID_API_KEY=                        # leave blank = mock mode
EMAIL_FROM=no-reply@example.com

GOOGLE_CLIENT_ID=                        # leave blank = mock mode
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/calendar/oauth2callback

APP_BASE_URL=http://localhost:8000
```

---

## Database Schema

```
users
  id (PK, UUID)
  email (UNIQUE)
  hashed_password
  full_name
  role  ENUM(patient, doctor, admin)
  phone
  google_credentials_json    ← stored OAuth2 token for calendar
  created_at

doctor_profiles
  id (PK, UUID)
  user_id (FK → users)
  specialisation
  slot_duration_minutes
  working_hours (JSON string: {"mon": ["09:00","17:00"], ...})

doctor_leave
  id (PK, UUID)
  doctor_id (FK → doctor_profiles)
  leave_date
  reason

appointments
  id (PK, UUID)
  patient_id (FK → users)
  doctor_id (FK → doctor_profiles)
  slot_start                 ─┐ UNIQUE constraint on (doctor_id, slot_start)
  slot_end                    │ ← this is the double-booking guard
  status  ENUM(booked, cancelled, completed)
  symptoms_text
  pre_visit_summary_json     ← urgency, chief_complaint, suggested_questions
  urgency_level  ENUM(Low, Medium, High)
  clinical_notes
  prescription_json          ← list of {drug, dose, frequency_per_day, duration_days}
  post_visit_summary_text
  patient_calendar_event_id
  doctor_calendar_event_id
  created_at / updated_at

medication_reminders
  id (PK, UUID)
  appointment_id (FK)
  patient_id (FK)
  drug_name
  scheduled_time
  sent (bool)
  sent_at

notification_log
  id (PK, UUID)
  recipient_email
  subject / body
  related_appointment_id (FK)
  status  ENUM(pending, sent, failed)
  attempts
  last_error
  created_at / sent_at
```

---

## API Reference

All endpoints return JSON. Protected routes require `Authorization: Bearer <token>`.

### Auth
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, full_name}` | Patient self-registration |
| POST | `/auth/login` | `{email, password}` | Returns JWT token |

### Admin
| Method | Path | Body | Description |
|---|---|---|---|
| POST | `/admin/doctors` | `DoctorCreate` | Create doctor account + profile |
| GET | `/admin/doctors` | — | List all doctors |
| POST | `/admin/doctors/{id}/leave` | `{leave_date, reason?}` | Mark leave; auto-cancels & notifies affected patients |

### Patient
| Method | Path | Description |
|---|---|---|
| GET | `/patient/doctors?specialisation=X` | Search doctors |
| GET | `/patient/doctors/{id}/slots?day=YYYY-MM-DD` | Available time slots |
| POST | `/patient/appointments/book` | Book a slot |
| POST | `/patient/appointments/{id}/symptoms` | Submit symptoms (triggers AI pre-visit summary) |
| GET | `/patient/appointments` | My appointments |

### Doctor
| Method | Path | Description |
|---|---|---|
| GET | `/doctor/appointments` | My schedule with pre-visit summaries |
| GET | `/doctor/appointments/{id}/pre-visit-summary` | Patient's AI symptom summary |
| POST | `/doctor/appointments/{id}/post-visit` | Submit notes + prescription (triggers post-visit summary + reminders) |

### Calendar
| Method | Path | Description |
|---|---|---|
| GET | `/calendar/connect` | Returns Google OAuth consent URL |
| GET | `/calendar/oauth2callback` | OAuth2 redirect handler (set as redirect URI in Google Console) |

**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)

---

## LLM Prompts

### Pre-visit (symptom summary)
```
Analyse these symptoms and return ONLY valid JSON with keys
"urgency_level" (Low/Medium/High), "chief_complaint" (short string),
and "suggested_questions" (array of exactly 3 strings the doctor
should ask). Symptoms: <symptoms_text>
```

### Post-visit (patient-friendly summary)
```
Convert these clinical notes into a patient-friendly summary with
a medication schedule and follow-up steps. Use plain, reassuring
language a non-medical person can understand. Clinical notes:
<clinical_notes>. Prescription: <prescription_text>
```

Both prompts have graceful fallbacks — if the LLM call fails for any reason, the system continues with a templated stub and flags it as non-AI-generated. The appointment is never blocked by LLM failure.

---

## Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Google Calendar API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Add Authorized redirect URI: `http://localhost:8000/calendar/oauth2callback`  
   (for production: `https://your-domain.com/calendar/oauth2callback`)
7. Download credentials and copy **Client ID** and **Client Secret** to `.env`
8. On the **OAuth consent screen**, add your test users (or publish the app)

Users connect their calendar from their portal (patient or doctor) via the "Connect Calendar" tab.

---

## Deployment (Render.com — free tier)

1. Push the project to GitHub
2. Create a new **Web Service** on [Render](https://render.com)
3. Build command: `pip install -r requirements.txt && python seed_admin.py`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add all environment variables from `.env` in the Render dashboard
6. For persistent data, add a **PostgreSQL** database on Render and set `DATABASE_URL`

**Railway** and **Fly.io** work identically — same build/start commands.

---

## Project Structure

```
healthcare-appointment-manager/
├── app/
│   ├── main.py              ← FastAPI app, router registration, scheduler startup
│   ├── config.py            ← All settings from environment variables
│   ├── database.py          ← SQLAlchemy engine + session
│   ├── auth.py              ← JWT, password hashing, role dependencies
│   ├── models/models.py     ← All DB models
│   ├── schemas/             ← Pydantic request/response schemas
│   ├── routers/             ← auth, admin, patient, doctor, calendar
│   ├── services/
│   │   ├── booking_service.py   ← Slot availability + concurrency-safe booking
│   │   ├── llm_service.py       ← Pre/post-visit summaries with fallback
│   │   ├── email_service.py     ← SendGrid + retry-friendly notification log
│   │   ├── calendar_service.py  ← Google Calendar CRUD
│   │   └── scheduler.py         ← APScheduler background jobs
│   └── utils/
├── static/                  ← Plain HTML/JS frontend (served by FastAPI)
│   ├── index.html           ← Login / register
│   ├── patient.html         ← Patient portal
│   ├── doctor.html          ← Doctor portal
│   ├── admin.html           ← Admin portal
│   └── style.css
├── seed_admin.py            ← One-time admin account seeder
├── run.py                   ← Dev server entrypoint
├── requirements.txt
└── .env.example
```

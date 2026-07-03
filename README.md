# Healthcare Appointment & Follow-up Manager

A full-stack healthcare platform with role-based access, AI symptom summaries, medication reminders, email notifications, and Google Calendar integration.

**Stack:** FastAPI · SQLAlchemy · SQLite (local) / PostgreSQL (production, via Neon) · APScheduler · Google Gemini API · SendGrid · Google Calendar API · Plain HTML/JS

**Live demo:** `https://healthcare-appointment-manager-6baq.onrender.com`

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

# 6. (Optional) Seed demo doctors, patients, and sample appointments
python seed_demo_data.py

# 7. Start the server
python run.py
# → Open http://localhost:8000
```

**Default admin credentials (change immediately, especially in production):**
- Email: `admin@healthbook.com`
- Password: `admin123`

---

## Mock Modes (no API keys needed to develop)

Every external integration has a mock mode that activates automatically when the corresponding key is absent from `.env`:

| Service | Key needed | Mock behaviour |
|---|---|---|
| LLM (Google Gemini) | `GEMINI_API_KEY` | Returns a hardcoded-but-functional pre/post-visit summary |
| Email | `SENDGRID_API_KEY` | Prints the email to the server log instead of sending |
| Google Calendar | `GOOGLE_CLIENT_ID` | Returns fake event IDs; all calendar calls log to console |

This means you can run the full booking flow, symptom submission, post-visit notes, and reminders **without any API keys**.

---

## Environment Variables (`.env.example`)

```env
DATABASE_URL=sqlite:///./app.db          # or postgresql://user:pass@host/db (Neon, Render, etc.)
JWT_SECRET=change-me-to-long-random-string
JWT_EXPIRE_MINUTES=1440

GEMINI_API_KEY=                          # leave blank = mock mode
LLM_MODEL=gemini-flash-latest

SENDGRID_API_KEY=                        # leave blank = mock mode
EMAIL_FROM=no-reply@example.com

GOOGLE_CLIENT_ID=                        # leave blank = mock mode
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/calendar/oauth2callback

APP_BASE_URL=http://localhost:8000
```

**Never commit `.env` or paste real key values anywhere public — only `.env.example` (with blank values) belongs in version control.**

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

**Interactive docs:** `/docs` (Swagger UI) — locally at `http://localhost:8000/docs`, or on your deployed URL.

---

## LLM Prompts (Google Gemini)

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

Both prompts have graceful fallbacks — if the Gemini API call fails for any reason (rate limit, timeout, malformed response), the system continues with a templated stub and flags it as non-AI-generated (`ai_generated: false`). The appointment flow is never blocked by LLM failure.

Gemini's free tier is rate-limited (roughly 15 requests/minute, 1,500/day on `gemini-flash-latest` as of writing — check [Google's current limits](https://ai.google.dev/gemini-api/docs/rate-limits) as these change). The fallback stub design means hitting these limits degrades gracefully rather than breaking bookings.

---

## Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or use existing)
3. Enable **Google Calendar API**
4. Go to **Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Web application**
6. Add Authorized redirect URI: `http://localhost:8000/calendar/oauth2callback`
   (for production: `https://<your-render-url>.onrender.com/calendar/oauth2callback`)
7. Download credentials and copy **Client ID** and **Client Secret** to `.env`
8. On the **OAuth consent screen**, add your test users (or publish the app)

Users connect their calendar from their portal (patient or doctor) via the "Connect Calendar" tab.

---

## Deployment (Render.com free tier + Neon Postgres)

Render's own free PostgreSQL expires 30 days after creation. **Neon's free Postgres tier has no expiration**, so this project pairs Render (compute) with Neon (database) for a fully free, persistent setup.

1. **Database:** Create a free project at [neon.tech](https://neon.tech) → copy the connection string it gives you
2. **Push to GitHub** — make sure `.env` and `app.db` are gitignored
3. **Python version pin:** add a `.python-version` file to the repo root containing:
   ```
   3.11.9
   ```
   (Render's default Python version can be too new for some pinned dependencies like `pydantic-core`, which lack prebuilt wheels for the latest Python — pinning avoids a source-compile failure during build.)
4. **Create a Web Service** on [Render](https://render.com), connected to your GitHub repo
5. **Build command:**
   ```
   pip install -r requirements.txt && python seed_admin.py
   ```
6. **Start command:**
   ```
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
7. **Environment variables** (set in Render's dashboard, not committed to the repo):

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | your Neon connection string |
   | `JWT_SECRET` | long random string |
   | `JWT_EXPIRE_MINUTES` | `1440` |
   | `GEMINI_API_KEY` | your Gemini key |
   | `LLM_MODEL` | `gemini-flash-latest` |
   | `SENDGRID_API_KEY` | blank for mock mode, or your key |
   | `EMAIL_FROM` | `no-reply@yourdomain.com` |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | if using Calendar |
   | `GOOGLE_REDIRECT_URI` | `<your-render-url>/calendar/oauth2callback` |
   | `APP_BASE_URL` | `<your-render-url>` |
   | `PYTHON_VERSION` | `3.11.9` (backup to the `.python-version` file) |

8. Deploy, then visit `/docs` to confirm the API is live, and `/static/index.html` for the frontend

**Free tier behavior:** the service spins down after 15 minutes of inactivity; the first request afterward takes ~30–60 seconds (cold start) while it spins back up. This is expected, not a bug.

**Railway** and **Koyeb** work with the same build/start commands as alternatives if needed. **Fly.io** no longer offers a free tier for new signups, and **PythonAnywhere**'s free tier doesn't support ASGI apps like FastAPI.

---

## Project Structure

```
healthcare-appointment-manager/
├── app/
│   ├── main.py              ← FastAPI app, router registration, scheduler startup
│   ├── config.py            ← All settings from environment variables (Settings class)
│   ├── database.py          ← SQLAlchemy engine + session
│   ├── auth.py               ← JWT, password hashing, role dependencies
│   ├── models/models.py     ← All DB models
│   ├── schemas/             ← Pydantic request/response schemas
│   ├── routers/             ← auth, admin, patient, doctor, calendar
│   ├── services/
│   │   ├── booking_service.py   ← Slot availability + concurrency-safe booking
│   │   ├── llm_service.py       ← Pre/post-visit summaries via Gemini, with fallback
│   │   ├── email_service.py     ← SendGrid + retry-friendly notification log
│   │   ├── calendar_service.py  ← Google Calendar CRUD
│   │   └── scheduler.py         ← APScheduler background jobs
│   └── utils/
├── static/                  ← Plain HTML/JS frontend (served by FastAPI)
│   ├── index.html           ← Login / register
│   ├── patient.html         ← Patient portal
│   ├── doctor.html          ← Doctor portal
│   ├── admin.html           ← Admin portal (create doctors, mark leave)
│   └── style.css            ← Shared styles, incl. per-role page background tints
├── seed_admin.py            ← One-time admin account seeder
├── seed_demo_data.py        ← Seeds demo doctors, patients, sample appointments
├── run.py                   ← Dev server entrypoint
├── requirements.txt
├── .python-version          ← Pins Python 3.11.9 for Render
└── .env.example
```

---

## Security Notes

- Never commit `.env`, real API keys, or database credentials to the repository — `.gitignore` should exclude `.env` and `app.db`
- The seeded default admin password (`admin123`) must be changed immediately after first login on any deployed instance, since it's publicly documented
- If a real API key is ever accidentally exposed (chat, commit history, screenshot), rotate it immediately at the provider (Google AI Studio for Gemini, SendGrid dashboard, Google Cloud Console for OAuth secrets) — assume it's compromised the moment it's exposed, regardless of where

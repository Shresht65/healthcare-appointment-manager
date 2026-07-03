import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth_router, admin_router, patient_router, doctor_router, calendar_router
from app.services.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Healthcare Appointment & Follow-up Manager",
    description="Booking, AI symptom summaries, post-visit summaries, email + calendar sync.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables on startup (fine for this project's scope; use Alembic
# migrations instead if this grows into a long-lived production app).
Base.metadata.create_all(bind=engine)

app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(patient_router.router)
app.include_router(doctor_router.router)
app.include_router(calendar_router.router)

app.mount("/static", StaticFiles(directory="static", html=True), name="static")

_scheduler = None


@app.on_event("startup")
def on_startup():
    global _scheduler
    _scheduler = start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    if _scheduler:
        _scheduler.shutdown()


@app.get("/")
def root():
    return {
        "message": "Healthcare Appointment & Follow-up Manager API",
        "docs": "/docs",
        "frontend": "/static/index.html",
    }


@app.get("/health")
def health():
    return {"status": "ok"}

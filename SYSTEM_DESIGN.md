# System Design: Healthcare Appointment & Follow-up Manager

## 1. Double-Booking Prevention

The trickiest reliability problem in any booking system is two patients claiming the same slot simultaneously. A naive approach — "check if slot is free, then insert if yes" — fails under concurrency because both requests can pass the check before either has committed the insert.

This system uses a two-layer defence:

**Layer 1 — Database-level UNIQUE constraint:**  
The `appointments` table carries a `UNIQUE(doctor_id, slot_start)` constraint. This constraint is enforced by the database engine, not the application layer, so it holds correctly even across multiple web workers or server processes. When two concurrent booking requests race, one INSERT wins and commits; the database rejects the second with an `IntegrityError`. The application catches this exception, rolls back the transaction, and returns a clean "slot just got taken — please choose another" response to the user. The patient is never silently double-booked, and the system never crashes.

**Layer 2 — Application-level availability check (UI only):**  
Before showing available slots to a patient, the API computes open slots by subtracting already-booked appointments and leave days from the doctor's working hours. This check exists only to display sensible options in the UI — it is not trusted as a booking gate. Any slot that disappears between the display check and the confirm-click is caught cleanly by Layer 1.

This design means the concurrency safety guarantee is held at the data layer, where it belongs.

---

## 2. Doctor Leave Conflict Handling

When an admin (or doctor) marks a leave date, the system must handle existing bookings on that date — not just block future ones.

**The flow:**
1. A `DoctorLeave` record is inserted for the target date.
2. The system queries `appointments` for all rows with `doctor_id = X`, `slot_start` falling within the leave date, and `status = booked`.
3. Each affected appointment is set to `cancelled`.
4. For each cancellation: the patient's Google Calendar event is deleted (if connected), the doctor's event is deleted, and a cancellation email is sent to the patient.
5. The API response reports how many appointments were cancelled and which patient emails were notified.

Future booking attempts on that date are blocked by the availability check in `get_available_slots`, which queries leave days and returns an empty slot list for any leave date.

The notification step uses the same `send_email` path as all other emails, meaning failures are logged to `notification_log` and retried by the background scheduler — no cancellation notification is silently dropped.

---

## 3. Slot Hold Mechanism

This system does not implement a time-based "soft hold" (reserving a slot for N minutes while a patient fills in a form), for a deliberate reason: the spec requires preventing double-booking, not preventing competition. A soft hold adds significant complexity (expiry logic, hold-clearing jobs, stale hold cleanup) and introduces new failure modes while providing only marginal UX benefit for a low-concurrency clinic system.

Instead, the UX is designed to minimise the race window:
- Available slots are fetched fresh when a patient selects a date (not at page load).
- Booking and symptom submission are separated — a patient books first (fast, one click), then fills in symptoms on the confirmed appointment. The race window is the time between selecting a slot and clicking "Confirm" — seconds, not minutes.
- If a race is lost, the user gets an immediate, actionable error message prompting them to pick another slot.

For high-concurrency clinical deployments, a Redis-backed slot lock with a 90-second TTL could be added to `booking_service.py` as a Layer 0 above the DB constraint, reducing retry rates. For the current scope, the DB constraint is sufficient.

---

## 4. Notification Failure Handling

Emails can fail for many reasons: transient network errors, SendGrid rate limits, invalid addresses, or temporary service outages. The system handles this with a persistent retry queue rather than fire-and-forget sends.

**Architecture:**
Every email send attempt — booking confirmations, cancellations, post-visit summaries, medication reminders — writes a `NotificationLog` record before attempting delivery. The record tracks `status` (pending / sent / failed), `attempts`, and `last_error`.

If the send succeeds, the record is marked `sent`. If it fails, the record stays `failed` with the error message stored. A background APScheduler job runs every 5 minutes and retries all `failed` records under a `MAX_ATTEMPTS` ceiling (5). After 5 failed attempts, the record is left as a permanent audit trail but no longer retried automatically — at which point an admin can inspect and intervene.

Medication reminders follow the same path: the scheduler runs every minute, finds `MedicationReminder` rows whose `scheduled_time` has passed and `sent = False`, fires an email through the `send_email` path (which logs and retries on failure), then marks the reminder sent.

**LLM failure handling:**  
LLM calls (pre-visit and post-visit summaries) are wrapped in try/except. Any failure — timeout, rate limit, malformed JSON response — falls through to a clearly labelled stub summary. The booking flow and post-visit submission continue regardless. The `ai_generated` flag in the summary JSON lets the frontend distinguish AI output from fallback output and display a warning to the user when appropriate.



## Summary

The system's reliability strategy concentrates complexity at the right layers: the database owns the double-booking guarantee, a persistent log owns notification reliability, and the application layer owns graceful degradation when external services (LLM, email, calendar) are unavailable. Each layer can fail independently without cascading into a system-wide outage.

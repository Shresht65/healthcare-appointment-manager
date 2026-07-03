"""
LLM integration for pre-visit symptom summaries and post-visit patient-friendly
summaries.

Failure handling (per spec: "LLM failures must be handled gracefully, system
should not break"):
  - If no API key is configured, runs in MOCK_MODE and returns a clearly
    labeled stub so the rest of the app (booking, calendar, email) can still
    be developed/tested end-to-end.
  - If the real API call raises ANY exception (timeout, rate limit, bad
    response), we catch it, log it, and return a safe fallback summary
    instead of letting the request fail. The appointment still gets booked;
    it just lacks an AI summary, which the doctor UI should flag clearly.
"""
import json
import logging
from typing import Optional

from google import genai

from app.config import settings

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None
if not settings.LLM_MOCK_MODE:
    _client = genai.Client(api_key=settings.GEMINI_API_KEY)


def _call_llm(prompt: str) -> Optional[str]:
    """Returns raw text response, or None on any failure."""
    if settings.LLM_MOCK_MODE:
        return None
    try:
        response = _client.models.generate_content(
            model=settings.LLM_MODEL,
            contents=prompt,
        )
        return response.text
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return None


def generate_pre_visit_summary(symptoms_text: str) -> dict:
    """
    Returns dict: {urgency_level, chief_complaint, suggested_questions: [..]}
    Falls back to a safe default (urgency=Medium, so it's never silently
    treated as low priority) if the LLM is unavailable or errors.
    """
    prompt = (
        "Analyse these symptoms and return ONLY valid JSON with keys "
        '"urgency_level" (Low/Medium/High), "chief_complaint" (short string), '
        'and "suggested_questions" (array of exactly 3 strings the doctor '
        f"should ask). Symptoms: {symptoms_text}"
    )
    raw = _call_llm(prompt)

    fallback = {
        "urgency_level": "Medium",
        "chief_complaint": symptoms_text[:120],
        "suggested_questions": [
            "Could you describe when these symptoms started?",
            "Have you taken any medication for this already?",
            "Is the symptom constant or does it come and go?",
        ],
        "ai_generated": False,
    }

    if raw is None:
        return fallback

    try:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        parsed["ai_generated"] = True
        # Defensive defaults in case the model omits a key
        parsed.setdefault("urgency_level", "Medium")
        parsed.setdefault("chief_complaint", symptoms_text[:120])
        parsed.setdefault("suggested_questions", fallback["suggested_questions"])
        return parsed
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse LLM pre-visit response: {e}")
        return fallback


def generate_post_visit_summary(clinical_notes: str, prescription: list) -> str:
    """
    Returns a patient-friendly summary string. Falls back to a simple
    templated summary (still useful, just not AI-polished) on failure.
    """
    prescription_text = "; ".join(
        f"{p['drug']} {p['dose']}, {p['frequency_per_day']}x/day for {p['duration_days']} days"
        for p in prescription
    ) or "No medication prescribed."

    prompt = (
        "Convert these clinical notes into a patient-friendly summary with "
        "a medication schedule and follow-up steps. Use plain, reassuring "
        "language a non-medical person can understand. Clinical notes: "
        f"{clinical_notes}. Prescription: {prescription_text}"
    )
    raw = _call_llm(prompt)

    if raw is not None:
        return raw

    # Fallback: simple template, not AI-polished but still functional
    return (
        f"Visit summary: {clinical_notes}\n\n"
        f"Medication schedule: {prescription_text}\n\n"
        "Please follow up with the clinic if symptoms worsen or persist "
        "beyond the expected recovery period. "
        "(Note: AI-generated summary unavailable; showing basic summary.)"
    )
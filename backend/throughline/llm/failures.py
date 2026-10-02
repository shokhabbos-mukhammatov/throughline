"""Turn an exception from a build into something a student can act on.

kind:
  syllabus  the syllabus itself couldn't be used (show the "paste the schedule" hint)
  service   the AI service refused or failed (credentials, quota, outage): not the student's fault
  internal  a bug on our side (details go to the log, not the page)
"""

from __future__ import annotations

AUTH_REASONS = ("API_KEY_INVALID", "API_KEY_EXPIRED", "PERMISSION_DENIED", "UNAUTHENTICATED", "SERVICE_DISABLED")


def describe_failure(exc: BaseException, syllabus_error: type[BaseException]) -> tuple[str, str]:
    if isinstance(exc, syllabus_error):
        return "syllabus", str(exc)
    try:
        from google.genai import errors as genai_errors
    except ImportError:  # pragma: no cover - the SDK is a hard dependency in production
        genai_errors = None
    if genai_errors is not None and isinstance(exc, genai_errors.APIError):
        text = f"{exc.status} {exc.message} {exc}"
        if exc.code in (401, 403) or any(r in text for r in AUTH_REASONS):
            return "service", ("The AI service rejected this site's credentials, so nothing could be mapped. "
                               "Your syllabus is fine: the site's Gemini key needs fixing. Try again later.")
        if exc.code == 429 or "RESOURCE_EXHAUSTED" in text:
            return "service", "The AI service is over its usage limit right now. Try again in a few minutes."
        if exc.code and exc.code >= 500:
            return "service", "The AI service didn't respond. Try again in a minute."
        return "service", f"The AI service returned an error ({exc.code} {exc.status}). Try again in a minute."
    if isinstance(exc, TimeoutError):
        return "service", "The AI service took too long to answer. Try again in a minute."
    return "internal", "Something went wrong on our side while mapping this course. Try again; if it keeps happening, tell the site owner."

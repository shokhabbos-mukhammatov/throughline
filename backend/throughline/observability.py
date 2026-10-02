"""Logging that Cloud Logging understands, and per-request ids that tie a user-visible error to its log entry."""

from __future__ import annotations

import contextvars
import json
import logging
import sys

request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
trace: contextvars.ContextVar[str] = contextvars.ContextVar("trace", default="")


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Cloud Logging maps `severity`, `message` and the trace field automatically."""

    def __init__(self, project: str | None):
        super().__init__()
        self.project = project

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        if record.exc_info:
            entry["message"] += "\n" + self.formatException(record.exc_info)
            # Error Reporting groups entries that carry a stack trace and this type.
            entry["@type"] = "type.googleapis.com/google.devtools.clouderrorreporting.v1beta1.ReportedErrorEvent"
            entry["serviceContext"] = {"service": "throughline"}
        if rid := request_id.get():
            entry["request_id"] = rid
        if (t := trace.get()) and self.project:
            entry["logging.googleapis.com/trace"] = f"projects/{self.project}/traces/{t}"
        return json.dumps(entry, ensure_ascii=False)


def setup_logging(fmt: str, project: str | None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter(project))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    for noisy in ("httpx", "google_genai.models", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

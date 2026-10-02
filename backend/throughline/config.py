"""Runtime configuration, read once from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Gemini: either an AI Studio key (local dev) or Vertex AI (Cloud Run).
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    use_vertex: bool = field(default_factory=lambda: _flag("GOOGLE_GENAI_USE_VERTEXAI"))
    gcp_project: str | None = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    gcp_location: str = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_LOCATION", "global"))
    model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    embed_model: str = field(default_factory=lambda: os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001"))
    embed_dim: int = field(default_factory=lambda: int(os.getenv("EMBED_DIM", "768")))
    # Embedding models are served from regional endpoints on Vertex AI.
    embed_location: str = field(default_factory=lambda: os.getenv("GEMINI_EMBED_LOCATION", "us-central1"))
    # Independent prerequisite-mapping runs per batch; a concept is kept when a majority propose it.
    mapping_samples: int = field(default_factory=lambda: int(os.getenv("MAPPING_SAMPLES", "3")))
    # "low" keeps structured jobs fast on Gemini 3 models; empty disables the hint.
    thinking_level: str = field(default_factory=lambda: os.getenv("GEMINI_THINKING_LEVEL", "low"))
    map_thinking_level: str = field(default_factory=lambda: os.getenv("GEMINI_MAP_THINKING_LEVEL", "medium"))
    # Force the offline heuristic engine even when a key is present (tests, no-network demos).
    offline: bool = field(default_factory=lambda: _flag("THROUGHLINE_OFFLINE"))

    store: str = field(default_factory=lambda: os.getenv("STORE", "memory"))  # memory | firestore
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", ".data"))
    persist: bool = field(default_factory=lambda: _flag("PERSIST", True))

    auth_mode: str = field(default_factory=lambda: os.getenv("AUTH_MODE", "demo"))  # demo | firebase
    static_dir: str | None = field(default_factory=lambda: os.getenv("STATIC_DIR"))
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_MB", "15")))
    # Fetch course entries from bulletin.sfsu.edu (falls back to a built-in snapshot when off or unreachable).
    bulletin_live: bool = field(default_factory=lambda: _flag("BULLETIN_LIVE", True))
    # Instructors see a heatmap cell only once this many students have answered (k-anonymity).
    min_cell: int = field(default_factory=lambda: int(os.getenv("MIN_CELL_STUDENTS", "5")))

    # Background jobs: "inline" (thread pool, local) or "cloudtasks" (durable, production).
    build_queue: str = field(default_factory=lambda: os.getenv("BUILD_QUEUE", "inline"))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", ""))  # the service's own https URL
    tasks_location: str = field(default_factory=lambda: os.getenv("TASKS_LOCATION", "us-central1"))
    tasks_queue: str = field(default_factory=lambda: os.getenv("TASKS_QUEUE", "course-builds"))
    tasks_invoker: str = field(default_factory=lambda: os.getenv("TASKS_INVOKER_SA", ""))  # identity Cloud Tasks signs as
    # "json" emits one JSON object per line, which Cloud Logging turns into structured, searchable entries.
    log_format: str = field(default_factory=lambda: os.getenv("LOG_FORMAT", "text"))
    # Firebase web config (public values the browser needs to sign in; not secrets).
    firebase_api_key: str = field(default_factory=lambda: os.getenv("FIREBASE_API_KEY", ""))
    firebase_auth_domain: str = field(default_factory=lambda: os.getenv("FIREBASE_AUTH_DOMAIN", ""))
    firebase_app_id: str = field(default_factory=lambda: os.getenv("FIREBASE_APP_ID", ""))
    # Comma-separated email domains allowed to add courses with Google sign-in (empty = any Google account).
    allowed_email_domains: tuple[str, ...] = field(default_factory=lambda: tuple(
        d.strip().lower().lstrip("@") for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()))

    @property
    def gemini_configured(self) -> bool:
        if self.offline:
            return False
        return bool(self.gemini_api_key) or (self.use_vertex and bool(self.gcp_project))


settings = Settings()

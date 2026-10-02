"""Background jobs (course builds and coverage re-checks).

Two queues with one interface:
- inline: a thread pool in this process (local development, tests). Jobs left unfinished by a restart are
  picked up again at startup.
- cloudtasks: Google Cloud Tasks calls back POST /api/internal/jobs with an OIDC token for a dedicated service
  account, so a job survives restarts and redeploys and is retried if the instance dies mid-build.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .config import Settings
from .ctx import Ctx
from .mapping import build_course, recheck_coverage

log = logging.getLogger(__name__)

JOB_PATH = "/api/internal/jobs"


def run_job(ctx: Ctx, kind: str, course_id: str, code: str = "") -> None:
    if kind == "build":
        build_course(ctx, course_id, code)
    elif kind == "recheck":
        recheck_coverage(ctx, course_id)
    else:
        raise ValueError(f"unknown job kind {kind!r}")


class InlineQueue:
    name = "inline"

    def __init__(self, ctx: Ctx, workers: int = 2):
        self.ctx = ctx
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def submit(self, kind: str, course_id: str, code: str = "") -> None:
        def run():
            try:
                run_job(self.ctx, kind, course_id, code)
            except Exception:
                log.exception("job %s for %s failed", kind, course_id)

        self.pool.submit(run)

    def resume_unfinished(self) -> int:
        """Restart builds a previous process left queued or running (their thread died with it)."""
        stuck = [c for c in self.ctx.catalog.all() if c.build.status in ("queued", "running")]
        for course in stuck:
            log.info("resuming unfinished build of %s", course.id)
            self.submit("build", course.id, course.code)
        return len(stuck)


class CloudTasksQueue:
    name = "cloudtasks"

    def __init__(self, settings: Settings, client_factory: Callable | None = None):
        if not (settings.gcp_project and settings.public_url and settings.tasks_invoker):
            raise RuntimeError("BUILD_QUEUE=cloudtasks needs GOOGLE_CLOUD_PROJECT, PUBLIC_URL and TASKS_INVOKER_SA")
        self.s = settings
        if client_factory is None:
            from google.cloud import tasks_v2

            client_factory = tasks_v2.CloudTasksClient
        self.client = client_factory()
        self.parent = f"projects/{settings.gcp_project}/locations/{settings.tasks_location}/queues/{settings.tasks_queue}"

    def submit(self, kind: str, course_id: str, code: str = "") -> None:
        url = self.s.public_url.rstrip("/") + JOB_PATH
        task = {
            "http_request": {
                "http_method": "POST",
                "url": url,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"kind": kind, "course_id": course_id, "code": code}).encode(),
                "oidc_token": {"service_account_email": self.s.tasks_invoker, "audience": self.s.public_url.rstrip("/")},
            },
            # A full build takes 1-2 minutes; give it room, well under Cloud Run's request timeout.
            "dispatch_deadline": {"seconds": 600},
        }
        self.client.create_task(request={"parent": self.parent, "task": task})
        log.info("queued %s job for %s on Cloud Tasks", kind, course_id)

    def resume_unfinished(self) -> int:
        return 0  # Cloud Tasks keeps and retries its own tasks.


def make_queue(ctx: Ctx):
    if ctx.settings.build_queue == "cloudtasks":
        return CloudTasksQueue(ctx.settings)
    return InlineQueue(ctx)


def verify_task_token(settings: Settings, authorization: str, verifier: Callable | None = None) -> None:
    """Accept only Cloud Tasks calls signed for our service URL by the dedicated invoker service account."""
    if not authorization.startswith("Bearer "):
        raise PermissionError("missing bearer token")
    if verifier is None:
        from google.auth.transport import requests as g_requests
        from google.oauth2 import id_token

        def verifier(token, audience):
            return id_token.verify_oauth2_token(token, g_requests.Request(), audience=audience)

    claims = verifier(authorization[7:], settings.public_url.rstrip("/"))
    if claims.get("email") != settings.tasks_invoker or not claims.get("email_verified", False):
        raise PermissionError("token is not from the Cloud Tasks invoker account")

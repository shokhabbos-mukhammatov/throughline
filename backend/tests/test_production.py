"""Production paths: Cloud Tasks queue, the internal job endpoint, Firebase identity rules, headers, Firestore."""

import os
import uuid
from dataclasses import replace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from throughline import api, auth, jobs
from throughline.config import Settings
from throughline.models import Course

client = TestClient(api.app)
PROD = Settings(offline=True, persist=False, bulletin_live=False, build_queue="cloudtasks", gcp_project="sf-hacks-tutor",
                public_url="https://throughline-1.us-central1.run.app", tasks_invoker="tasks@sf-hacks-tutor.iam.gserviceaccount.com")


def _request(headers: dict) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


# -- Cloud Tasks ----------------------------------------------------------------------------------------


def test_cloud_tasks_queue_sends_an_authenticated_http_task():
    sent = []

    class FakeClient:
        def create_task(self, request):
            sent.append(request)

    q = jobs.CloudTasksQueue(PROD, client_factory=FakeClient)
    q.submit("build", "crs_1", "DS 612")
    req = sent[0]
    assert req["parent"] == "projects/sf-hacks-tutor/locations/us-central1/queues/course-builds"
    http = req["task"]["http_request"]
    assert http["url"] == "https://throughline-1.us-central1.run.app/api/internal/jobs"
    assert http["oidc_token"] == {"service_account_email": PROD.tasks_invoker, "audience": PROD.public_url}
    assert b'"kind": "build"' in http["body"] and b"DS 612" in http["body"]


def test_cloud_tasks_queue_refuses_incomplete_config():
    with pytest.raises(RuntimeError):
        jobs.CloudTasksQueue(replace(PROD, tasks_invoker=""), client_factory=object)


def test_task_token_must_come_from_the_invoker_account():
    good = lambda token, audience: {"email": PROD.tasks_invoker, "email_verified": True, "aud": audience}  # noqa: E731
    other = lambda token, audience: {"email": "someone@example.com", "email_verified": True}  # noqa: E731
    jobs.verify_task_token(PROD, "Bearer x", verifier=good)
    with pytest.raises(PermissionError):
        jobs.verify_task_token(PROD, "Bearer x", verifier=other)
    with pytest.raises(PermissionError):
        jobs.verify_task_token(PROD, "", verifier=good)


def test_internal_job_endpoint_is_closed_in_inline_mode():
    r = client.post("/api/internal/jobs", json={"kind": "build", "course_id": "x"})
    assert r.status_code == 404


def test_internal_job_endpoint_rejects_unsigned_calls(monkeypatch):
    class Q:
        name = "cloudtasks"

    monkeypatch.setattr(api, "queue", Q())
    monkeypatch.setattr(api, "settings", PROD)
    r = client.post("/api/internal/jobs", json={"kind": "build", "course_id": "x"}, headers={"Authorization": "Bearer forged"})
    assert r.status_code == 403


def test_unfinished_builds_resume_after_a_restart(ctx):
    stuck = Course(owner="u", code="DS 612", syllabus_text="x" * 100)
    stuck.build.status = "running"
    done = Course(owner="u", code="CSC 648", syllabus_text="x" * 100)
    done.build.status = "ready"
    ctx.catalog.put(stuck)
    ctx.catalog.put(done)
    q = jobs.InlineQueue(ctx)
    submitted = []
    q.submit = lambda kind, cid, code="": submitted.append((kind, cid))
    assert q.resume_unfinished() == 1 and submitted == [("build", stuck.id)]


# -- identity ---------------------------------------------------------------------------------------------


FIREBASE = replace(PROD, auth_mode="firebase")


def _claims(provider, email="", verified=True):
    return lambda token, project: {"sub": "uid-1", "firebase": {"sign_in_provider": provider}, "email": email, "email_verified": verified}


def test_firebase_anonymous_visitors_can_study_but_not_add_courses():
    who = auth.identify(_request({"Authorization": "Bearer t"}), FIREBASE, verifier=_claims("anonymous"))
    assert who.uid == "uid-1" and not who.signed_in
    with pytest.raises(HTTPException) as e:
        auth.require_account(who, FIREBASE)
    assert e.value.status_code == 401


def test_firebase_google_accounts_can_add_courses_and_domains_can_be_limited():
    who = auth.identify(_request({"Authorization": "Bearer t"}), FIREBASE, verifier=_claims("google.com", "kim@sfsu.edu"))
    auth.require_account(who, FIREBASE)
    auth.require_account(who, replace(FIREBASE, allowed_email_domains=("sfsu.edu",)))
    outsider = auth.identify(_request({"Authorization": "Bearer t"}), FIREBASE, verifier=_claims("google.com", "kim@gmail.com"))
    with pytest.raises(HTTPException) as e:
        auth.require_account(outsider, replace(FIREBASE, allowed_email_domains=("sfsu.edu",)))
    assert e.value.status_code == 403


def test_firebase_rejects_missing_or_bad_tokens():
    with pytest.raises(HTTPException):
        auth.identify(_request({}), FIREBASE)

    def bad(token, project):
        raise ValueError("expired")

    with pytest.raises(HTTPException) as e:
        auth.identify(_request({"Authorization": "Bearer t"}), FIREBASE, verifier=bad)
    assert e.value.status_code == 401


# -- HTTP hardening -------------------------------------------------------------------------------------


def test_health_ready_and_security_headers():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["queue"] == "inline"
    for header in ("X-Request-Id", "X-Content-Type-Options", "Content-Security-Policy", "Referrer-Policy"):
        assert header in r.headers
    assert r.headers["Cache-Control"] == "no-store"
    assert client.get("/api/ready").json() == {"ok": True}
    assert client.get("/api/config").json() == {"auth": "demo"}


def test_unexpected_errors_do_not_leak_internals(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(api.bulletin, "lookup", boom)
    r = TestClient(api.app, raise_server_exceptions=False).get("/api/bulletin/DS%20612")
    assert r.status_code == 500 and "secret" not in r.text and "reference" in r.json()["detail"]


# -- Firestore (runs only against the emulator: FIRESTORE_EMULATOR_HOST=127.0.0.1:8085) --------------------


@pytest.mark.skipif(not os.getenv("FIRESTORE_EMULATOR_HOST"), reason="needs the Firestore emulator")
def test_firestore_store_round_trip_through_the_app_layers():
    from throughline.ctx import Ctx
    from throughline.llm.offline import OfflineEngine
    from throughline.seed import sample
    from throughline.store.firestore_store import FirestoreStore

    store = FirestoreStore(project="demo-throughline")
    ctx = Ctx(store=store, engine=OfflineEngine(), settings=Settings(offline=True, persist=False, bulletin_live=False))
    course = sample.create_sample(ctx, f"owner-{uuid.uuid4().hex[:6]}")
    again = ctx.catalog.get(course.id)
    repo = ctx.course(course.id)
    assert again is not None and again.build.status == "ready"
    assert len(repo.concepts.list()) >= 8 and repo.edges.list() and repo.enrollments.list()
    assert ctx.catalog.by_join_code(course.join_code).id == course.id
    repo.wipe()
    assert repo.concepts.list() == []


def test_json_logs_carry_severity_and_error_reporting_type():
    import json
    import logging

    from throughline.observability import JsonFormatter, request_id

    fmt = JsonFormatter("sf-hacks-tutor")
    request_id.set("abc123")
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "build failed", None, sys.exc_info())
    entry = json.loads(fmt.format(record))
    assert entry["severity"] == "ERROR" and entry["request_id"] == "abc123"
    assert "ValueError: boom" in entry["message"] and entry["@type"].endswith("ReportedErrorEvent")


# -- failures the student can act on ---------------------------------------------------------------------


def test_failures_are_classified_for_the_student():
    from google.genai import errors as genai_errors

    from throughline.llm.failures import describe_failure
    from throughline.mapping import BuildFailed

    bad_key = genai_errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                                       "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
    kind, msg = describe_failure(bad_key, BuildFailed)
    assert kind == "service" and "syllabus is fine" in msg and "API key not valid" not in msg
    quota = genai_errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    assert describe_failure(quota, BuildFailed)[0] == "service"
    assert describe_failure(BuildFailed("No timeline found."), BuildFailed) == ("syllabus", "No timeline found.")
    kind, msg = describe_failure(KeyError("secret internals"), BuildFailed)
    assert kind == "internal" and "secret" not in msg


def test_a_build_with_a_rejected_key_says_so(ctx, monkeypatch):
    from google.genai import errors as genai_errors

    from throughline import mapping

    def rejected(*a, **k):
        raise genai_errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT",
                                                       "details": [{"reason": "API_KEY_INVALID"}]}})

    monkeypatch.setattr(ctx.engine, "parse_syllabus", rejected)
    course = Course(owner="u", code="DS 612", syllabus_text="Week 1 Intro to regression\n" * 10)
    ctx.catalog.put(course)
    mapping.build_course(ctx, course.id, "DS 612")
    b = ctx.catalog.get(course.id).build
    assert b.status == "error" and b.error_kind == "service" and "credentials" in b.error


def test_deep_health_makes_a_real_model_call_and_caches_it(monkeypatch):
    calls = []

    class Engine:
        label, online = "fake", True

        def ping(self):
            calls.append(1)

    monkeypatch.setattr(api, "engine", Engine())
    monkeypatch.setattr(api, "_gemini_check", {"at": 0.0, "result": None})
    r = client.get("/api/health?deep=1")
    assert r.status_code == 200 and r.json()["gemini"] == "ok"
    client.get("/api/health?deep=1")
    assert len(calls) == 1, "second check within 5 minutes is served from cache"

    class Broken(Engine):
        def ping(self):
            raise TimeoutError()

    monkeypatch.setattr(api, "engine", Broken())
    monkeypatch.setattr(api, "_gemini_check", {"at": 0.0, "result": None})
    r = client.get("/api/health?deep=1")
    assert r.status_code == 503 and r.json()["gemini"] != "ok"

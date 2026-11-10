"""HTTP API (FastAPI). Serves the built frontend too, so one Cloud Run service runs everything."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import background as bg
from . import bulletin
from . import revise
from .assessment import NotFound, adaptive_next, answer, study
from .auth import Identity, identify, require_account
from .config import settings
from .ctx import Ctx
from .heatmap import class_view
from .ingest import UnsupportedFile, guess_mime, syllabus_text
from .llm import make_engine
from .graph import depths
from .jobs import JOB_PATH, make_queue, run_job, verify_task_token
from .materials import build_material
from .models import Course, Enrollment, Material, PrereqDoc, PriorCourse, Revision
from .observability import request_id, setup_logging, trace
from .readiness import Snapshot, concept_view, plan, timeline
from .seed import sample
from .store import make_store
from .textutil import course_code, redact

setup_logging(settings.log_format, settings.gcp_project)
log = logging.getLogger("throughline")

store = make_store(settings)
engine = make_engine(settings)
services = Ctx(store=store, engine=engine, settings=settings)
queue = make_queue(services)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    resumed = queue.resume_unfinished()
    log.info("started: engine=%s store=%s queue=%s auth=%s resumed_builds=%d",
             engine.label, settings.store, queue.name, settings.auth_mode, resumed)
    yield


app = FastAPI(title="Throughline", version="0.3.0", lifespan=lifespan,
              docs_url=None if settings.auth_mode == "firebase" else "/docs", redoc_url=None)

# The page loads fonts from Google Fonts; KaTeX and React set inline styles. Everything else is same-origin,
# plus the Firebase sign-in endpoints when sign-in is on.
_CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://apis.google.com https://www.gstatic.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self' https://*.googleapis.com https://securetoken.googleapis.com https://identitytoolkit.googleapis.com",
    "frame-src https://*.firebaseapp.com https://accounts.google.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:12]
    request_id.set(rid)
    trace.set((request.headers.get("X-Cloud-Trace-Context") or "").split("/")[0])
    response = await call_next(request)
    response.headers["X-Request-Id"] = rid
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
def current_identity(request: Request) -> Identity:
    return identify(request, settings)


def current_uid(who: Identity = Depends(current_identity)) -> str:
    return who.uid


def account_uid(who: Identity = Depends(current_identity)) -> str:
    """For actions that spend model calls: a signed-in account, not an anonymous visitor."""
    require_account(who, settings)
    return who.uid


def get_ctx() -> Ctx:
    return services


def _course(course_id: str) -> Course:
    course = services.catalog.get(course_id)
    if course is None:
        raise HTTPException(404, "Course not found")
    return course


def _owned(course_id: str, uid: str) -> Course:
    course = _course(course_id)
    if course.owner != uid:
        raise HTTPException(403, "Only the person who added this course can do that")
    return course


def _snapshot(course: Course, uid: str) -> Snapshot:
    return Snapshot.load(course, services.course(course.id), uid, services.now().date())


def _submit(kind: str, course_id: str, code: str = "") -> None:
    try:
        queue.submit(kind, course_id, code)
    except Exception as exc:
        log.exception("could not queue %s job for %s", kind, course_id)
        course = services.catalog.get(course_id)
        if course is not None:
            course.build.status, course.build.error = "error", "The build couldn't be queued. Try again in a minute."
            services.catalog.put(course)
        raise HTTPException(503, "The build queue is unavailable. Try again in a minute.") from exc


# Every course build costs model calls; limit them per person and overall.
_builds: dict[str, deque] = {}
_builds_lock = threading.Lock()
BUILDS_PER_HOUR_PER_USER = 8
BUILDS_PER_HOUR_TOTAL = 120
# Reading a notes file costs a few small model calls, far less than mapping a course.
NOTES_PER_HOUR_PER_USER = 30
NOTES_PER_HOUR_TOTAL = 400


def _allow_build(uid: str, kind: str = "build") -> None:
    now = time.time()
    per_user, total = (NOTES_PER_HOUR_PER_USER, NOTES_PER_HOUR_TOTAL) if kind == "notes" else (BUILDS_PER_HOUR_PER_USER, BUILDS_PER_HOUR_TOTAL)
    what = "files read" if kind == "notes" else "syllabi mapped"
    with _builds_lock:
        for key, limit in ((f"{kind}:{uid}", per_user), (f"{kind}:*", total)):
            q = _builds.setdefault(key, deque())
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= limit:
                raise HTTPException(429, f"Too many {what} in the last hour. Try again later.")
        _builds[f"{kind}:{uid}"].append(now)
        _builds[f"{kind}:*"].append(now)


async def _read_syllabus(file: UploadFile) -> str:
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"{file.filename} is larger than {settings.max_upload_mb} MB")
    try:
        return syllabus_text(engine, data, file.filename or "syllabus", guess_mime(file.filename or "", file.content_type))
    except UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc
_gemini_check: dict = {"at": 0.0, "result": None}
_gemini_check_lock = threading.Lock()


def _check_gemini() -> str:
    """Make one tiny Gemini call; cached (5 min if it works, 1 min if not) so this can't be used to burn quota."""
    from .llm.failures import describe_failure
    from .mapping import BuildFailed

    with _gemini_check_lock:
        age = time.time() - _gemini_check["at"]
        cached = _gemini_check["result"]
        if cached is not None and age < (300 if cached == "ok" else 60):
            return cached
        if not engine.online:
            result = "offline"
        else:
            try:
                engine.ping()
                result = "ok"
            except Exception as exc:
                log.exception("Gemini check failed")
                result = describe_failure(exc, BuildFailed)[1]
        _gemini_check.update(at=time.time(), result=result)
        return result


@app.get("/api/health")
def health(deep: bool = False):
    """Liveness: the process is up. Cheap; used by Cloud Run probes and the uptime check.
    deep=1 also proves Gemini answers (used by the post-deploy smoke test); 503 if it doesn't."""
    out = {"ok": True, "engine": engine.label, "online": engine.online, "store": settings.store,
           "queue": queue.name, "auth": settings.auth_mode}
    if deep:
        out["gemini"] = _check_gemini()
        if out["gemini"] != "ok":
            return JSONResponse({**out, "ok": False}, status_code=503)
    return out


@app.get("/api/ready")
def ready():
    """Readiness: the store answers. Returns 503 if it doesn't."""
    try:
        services.catalog.get("readiness-probe")  # Firestore reserves __names__
    except Exception as exc:
        log.exception("readiness check failed")
        raise HTTPException(503, "storage unavailable") from exc
    return {"ok": True}


@app.get("/api/config")
def client_config():
    """What the browser needs to start: how to sign in. Firebase web config values are public by design."""
    out: dict = {"auth": settings.auth_mode}
    if settings.auth_mode == "firebase":
        out["firebase"] = {"apiKey": settings.firebase_api_key, "authDomain": settings.firebase_auth_domain or f"{settings.gcp_project}.firebaseapp.com",
                           "projectId": settings.gcp_project, "appId": settings.firebase_app_id}
    return out


class JobBody(BaseModel):
    kind: str
    course_id: str
    code: str = ""


@app.post(JOB_PATH, include_in_schema=False)
def run_internal_job(body: JobBody, request: Request):
    """Called by Cloud Tasks only (OIDC token of the invoker service account); runs the job to completion."""
    if queue.name != "cloudtasks":
        raise HTTPException(404)
    try:
        verify_task_token(settings, request.headers.get("Authorization", ""))
    except Exception as exc:
        log.warning("rejected job call: %s", exc)
        raise HTTPException(403, "forbidden") from exc
    course = services.catalog.get(body.course_id)
    if course is None:
        return {"skipped": "course deleted"}
    retry = int(request.headers.get("X-CloudTasks-TaskRetryCount", "0") or 0)
    if retry and body.kind == "build" and course.build.status in ("ready", "error"):
        return {"skipped": "already finished"}  # a retry of a build that completed after the first attempt timed out
    run_job(services, body.kind, body.course_id, body.code)
    return {"done": True}


@app.get("/api/bulletin/{code}")
def bulletin_lookup(code: str):
    entry = bulletin.lookup(code, live=settings.bulletin_live)
    if entry is None:
        raise HTTPException(404, f"{course_code(code)} isn't in the Bulletin snapshot, and the live Bulletin didn't answer.")
    return {**entry.model_dump(), "prereq_groups": entry.groups()}


MAX_PREREQ_DOCS = 6


def _prereq_doc(code: str, text: str) -> PrereqDoc:
    if not code.strip():
        raise HTTPException(400, "Say which prerequisite course each syllabus is for")
    if len(text.strip()) < 20:  # a pasted topic list can be short; an empty read can't be evidence
        raise HTTPException(422, f"The {course_code(code)} syllabus looks empty. Try another file or paste the text.")
    return PrereqDoc(code=course_code(code), text=redact(text)[: bg.SYLLABUS_CHARS])


@app.post("/api/courses")
async def add_course(
    code: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    prereq_code: str = Form(""),
    prereq_file: UploadFile | None = File(None),
    prereqs: str = Form(""),  # JSON: [{"code": "DS 212", "text": "..."} or {"code": "ISYS 263", "file": 0}]
    prereq_files: list[UploadFile] | None = File(None),
    uid: str = Depends(account_uid),
):
    """Map a course from its syllabus. Syllabi of its listed prerequisites (any number, each a file or pasted text)
    become evidence of what those courses taught, for everyone in the class."""
    if file is None and not text.strip():
        raise HTTPException(400, "Upload the syllabus file or paste its text")
    raw = await _read_syllabus(file) if file is not None else text
    if len(raw.strip()) < 80:
        raise HTTPException(422, "That syllabus looks empty. Try another file or paste the text.")
    docs: dict[str, PrereqDoc] = {}
    if prereq_file is not None:
        doc = _prereq_doc(prereq_code, await _read_syllabus(prereq_file))
        docs[doc.code] = doc
    try:
        listed = json.loads(prereqs) if prereqs.strip() else []
    except ValueError:
        listed = None
    if not isinstance(listed, list) or not all(isinstance(x, dict) for x in listed):
        raise HTTPException(400, "Couldn't read the list of prerequisite syllabi")
    uploads = prereq_files or []
    for item in listed[:MAX_PREREQ_DOCS]:
        n = item.get("file")
        if isinstance(n, int) and 0 <= n < len(uploads):
            doc = _prereq_doc(str(item.get("code", "")), await _read_syllabus(uploads[n]))
        else:
            doc = _prereq_doc(str(item.get("code", "")), str(item.get("text", "")))
        docs[doc.code] = doc
    _allow_build(uid)
    entry = bulletin.lookup(code, live=settings.bulletin_live) if code.strip() else None
    course = Course(owner=uid, code=course_code(code) if code.strip() else "", title=entry.title if entry else "",
                    syllabus_text=redact(raw)[:150_000], prereq_docs=list(docs.values())[:MAX_PREREQ_DOCS])
    services.catalog.put(course)
    _submit("build", course.id, code)
    return course.public()


@app.post("/api/courses/{course_id}/prereq-syllabus")
async def add_prereq_syllabus(course_id: str, prereq_code: str = Form(...), file: UploadFile | None = File(None),
                              text: str = Form(""), uid: str = Depends(account_uid)):
    """Add a listed prerequisite's syllabus (a file or pasted text) as evidence for the class, then re-check coverage.
    One per prerequisite course; adding another for the same course replaces it."""
    course = _owned(course_id, uid)
    if file is None and not text.strip():
        raise HTTPException(400, "Upload the syllabus file or paste its text")
    doc = _prereq_doc(prereq_code, await _read_syllabus(file) if file is not None else text)
    others = [d for d in course.prereq_docs if d.code != doc.code]
    if len(others) >= MAX_PREREQ_DOCS:
        raise HTTPException(400, f"A course can keep up to {MAX_PREREQ_DOCS} prerequisite syllabi.")
    course.prereq_docs = others + [doc]
    course.build.stage = "Re-checking what prerequisites taught"
    services.catalog.put(course)
    _submit("recheck", course.id)
    return course.public()


@app.post("/api/demo/sample")
def demo_sample(uid: str = Depends(current_uid)):
    return sample.create_sample(services, uid).public()


@app.get("/api/courses/mine")
def my_courses(uid: str = Depends(current_uid)):
    return [c.public() for c in services.catalog.owned_by(uid)]


@app.get("/api/join/{join_code}")
def join(join_code: str):
    course = services.catalog.by_join_code(join_code)
    if course is None:
        raise HTTPException(404, "No course with that code")
    return course.public()


@app.get("/api/courses/{course_id}")
def course_detail(course_id: str, uid: str = Depends(current_uid)):
    course = _course(course_id)
    out = {**course.public(), "is_owner": course.owner == uid, "engine": {"label": engine.label, "online": engine.online}}
    if course.owner == uid:  # what deleting the course would remove, for its warning
        repo = services.course(course_id)
        out["confirm_name"] = course.confirm_name
        out["students"] = sum(1 for e in repo.enrollments.list() if not e.simulated and e.id != uid)
    if course.build.status != "ready":
        return out
    snap = _snapshot(course, uid)
    mine = services.course(course_id).enrollments.get(uid)
    out.update(
        week_now=snap.week_now,
        enrolled=mine is not None and mine.setup,
        enrollment={**snap.enrollment.model_dump(mode="json"), "met": bg.effective_met(snap.enrollment, course.groups())},
        # "A or B" requirements this student hasn't answered: asked before the plan and the quick check
        choices_needed=bg.unanswered_choices(course, snap.enrollment),
        timeline=timeline(snap),
        concepts=sorted((concept_view(snap, c) for c in snap.concepts.values()),
                        key=lambda v: (v["next_need"] is None, (v["next_need"] or {}).get("date", ""), v["name"])),
    )
    return out


class EnrollmentBody(BaseModel):
    # Listed prerequisite code -> "took" | "elsewhere" | "none" | "unsure". Replaces the earlier answers.
    met: dict[str, str] | None = Field(default=None, max_length=40)
    draft: bool = False  # save the answers without finishing setup (the add-course form does this)
    route: str | None = None  # older clients: one answer for the whole course
    prereq_taken: str | None = None  # older clients: the one alternative taken; "" clears it
    weekly_minutes: int | None = Field(default=None, ge=15, le=2400)
    self_report: dict[str, str] | None = None


@app.put("/api/courses/{course_id}/me")
def update_me(course_id: str, body: EnrollmentBody, uid: str = Depends(current_uid)):
    course = _course(course_id)
    repo = services.course(course.id)
    e = repo.enrollments.get(uid) or Enrollment(id=uid, setup=False)
    e.setup = e.setup or not body.draft
    if body.met is not None:
        e.met = {course_code(code): how for code, how in body.met.items()  # type: ignore[misc]
                 if code.strip() and how in ("took", "elsewhere", "none", "unsure")}
        e.route, e.prereq_taken = bg.route_of(e.met), None  # type: ignore[assignment]
    elif body.route in ("took_here", "equivalent", "permission", "unsure"):
        e.route = body.route  # type: ignore[assignment]
    if body.prereq_taken is not None:
        code = course_code(body.prereq_taken) if body.prereq_taken.strip() else ""
        options = {course_code(c) for c in course.official_prereqs}
        if code and code not in options:
            raise HTTPException(422, f"{code} isn't one of this course's listed prerequisites")
        e.prereq_taken = code or None
    if body.weekly_minutes is not None:
        e.weekly_minutes = body.weekly_minutes
    if body.self_report:
        valid = {c.id for c in repo.concepts.list()}
        for cid, v in body.self_report.items():
            if cid in valid and v in ("yes", "never", "unsure"):
                e.self_report[cid] = v  # type: ignore[assignment]
    repo.enrollments.put(e)
    return e.model_dump(mode="json")


@app.get("/api/courses/{course_id}/plan")
def get_plan(course_id: str, uid: str = Depends(current_uid)):
    return plan(_snapshot(_course(course_id), uid))


class CheckBody(BaseModel):
    session: list[str] = Field(default_factory=list, max_length=50)  # response ids answered in this check


@app.post("/api/courses/{course_id}/check/next")
def check_next(course_id: str, body: CheckBody, uid: str = Depends(current_uid)):
    course = _course(course_id)
    snap = _snapshot(course, uid)
    open_choices = bg.unanswered_choices(course, snap.enrollment)
    if open_choices:
        raise HTTPException(409, "Before the check, say which of these you took: " + "; ".join(" or ".join(g) for g in open_choices))
    return adaptive_next(snap, services.course(course.id), body.session)


@app.delete("/api/courses/{course_id}/me")
def delete_me(course_id: str, uid: str = Depends(current_uid)):
    """Delete this student's answers and settings for the course."""
    repo = services.course(_course(course_id).id)
    mine = [r.id for r in repo.responses.list(student=uid)]
    repo.responses.delete_many(mine)
    materials = [m.id for m in repo.materials.list(student=uid)]
    repo.materials.delete_many(materials)
    earlier = [p.id for p in repo.prior_courses.list(student=uid)]
    repo.prior_courses.delete_many(earlier)
    repo.enrollments.delete_many([uid])
    return {"deleted_responses": len(mine), "deleted_materials": len(materials), "deleted_courses": len(earlier)}


@app.get("/api/courses/{course_id}/background")
def list_background(course_id: str, uid: str = Depends(current_uid)):
    """The earlier courses this student added. Only they can see them."""
    repo = services.course(_course(course_id).id)
    names = {c.id: c.name for c in repo.concepts.list() if not c.removed}
    return [bg.view(p, names) for p in sorted(repo.prior_courses.list(student=uid), key=lambda p: p.created_at)]


@app.post("/api/courses/{course_id}/background")
async def add_prior_course(course_id: str, code: str = Form(...), title: str = Form(""), school: str = Form(""),
                           replaces: str = Form(""), text: str = Form(""), file: UploadFile | None = File(None),
                           uid: str = Depends(current_uid)):
    """Add a course you took before, at any school, with its syllabus (a file or pasted text) if you have it.
    The syllabus is compared with this course's map; while the map is still being built, that happens at the end."""
    course = _course(course_id)
    repo = services.course(course.id)
    name = " ".join(code.split())[:40]
    if len(name) < 2:
        raise HTTPException(400, "Name the course you took, for example CSE 206")
    if len(repo.prior_courses.list(student=uid)) >= bg.MAX_PRIOR_COURSES:
        raise HTTPException(400, f"You can keep up to {bg.MAX_PRIOR_COURSES} earlier courses per course. Remove one first.")
    data = await file.read() if file is not None else None
    if data and len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"{file.filename} is larger than {settings.max_upload_mb} MB")  # type: ignore[union-attr]
    given = bool(data) or bool(text.strip())
    if given:
        _allow_build(uid, "notes")  # reading and matching spends a few model calls
    filename = (file.filename or "syllabus") if file is not None else ""
    try:
        source, chunks = await run_in_threadpool(bg.read_syllabus, engine, data, filename,
                                                 guess_mime(filename, file.content_type if file is not None else None), text)
    except UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc
    if given and not chunks:
        raise HTTPException(422, "No text found in that syllabus. If it's a scan, try a clearer photo or paste the text.")
    # A bare course number is tidied ("cse206" -> "CSE 206"); anything else is kept as written.
    tidy = course_code(name) if re.fullmatch(r"[A-Za-z]{2,5}\s*-?\s*\d{3}[A-Za-z]?", name) else name
    prior = PriorCourse(student=uid, code=tidy, title=" ".join(title.split())[:120], school=" ".join(school.split())[:80],
                        replaces=course_code(replaces) if replaces.strip() else None, source=source, chunks=chunks)
    concepts = [c for c in repo.concepts.list() if not c.removed]
    if course.build.status == "ready" and chunks:
        await run_in_threadpool(bg.match_prior_course, engine, concepts, prior)
    repo.prior_courses.put(prior)
    log.info("prior course %s for %s: %d passages, %d matches", prior.id, course.id, len(prior.chunks), len(prior.matches))
    listed = {course_code(c) for c in course.official_prereqs}
    if uid == course.owner and chunks and not prior.school and course_code(prior.code) in listed and course.build.status == "ready":
        # the owner's copy of a listed prerequisite's syllabus is evidence for the whole class: re-check with it
        course.build.stage = "Re-checking what prerequisites taught"
        services.catalog.put(course)
        _submit("recheck", course.id)
    return bg.view(prior, {c.id: c.name for c in concepts})


@app.delete("/api/courses/{course_id}/background/{prior_id}")
def delete_prior_course(course_id: str, prior_id: str, uid: str = Depends(current_uid)):
    repo = services.course(_course(course_id).id)
    p = repo.prior_courses.get(prior_id)
    if p is None or p.student != uid:
        raise HTTPException(404, "Not found")
    repo.prior_courses.delete_many([p.id])
    return {"deleted": p.id}
MAX_MATERIALS = 12


def _material_view(m: Material, names: dict[str, str]) -> dict:
    covers: dict[str, list[str]] = {}
    for x in m.matches:
        if x.concept_id in names:
            covers.setdefault(x.concept_id, []).append(x.loc)
    return {"id": m.id, "filename": m.filename, "prereq_code": m.prereq_code, "kind": m.kind,
            "parts": len({c.loc for c in m.chunks}), "created_at": m.created_at.isoformat(),
            "covers": [{"concept_id": cid, "name": names[cid], "locs": sorted(set(locs), key=_loc_order)} for cid, locs in covers.items()]}


def _loc_order(loc: str) -> tuple[str, int]:
    word, _, num = loc.partition(" ")
    return (word, int(num) if num.isdigit() else 0)


@app.get("/api/courses/{course_id}/materials")
def list_materials(course_id: str, uid: str = Depends(current_uid)):
    repo = services.course(_course(course_id).id)
    names = {c.id: c.name for c in repo.concepts.list() if not c.removed}
    return [_material_view(m, names) for m in sorted(repo.materials.list(student=uid), key=lambda m: m.created_at)]


@app.post("/api/courses/{course_id}/materials")
async def add_material(course_id: str, file: UploadFile = File(...), prereq_code: str = Form(""), uid: str = Depends(current_uid)):
    """Upload your own notes, slides or handouts from a prerequisite course; they're matched to this course's map."""
    course = _course(course_id)
    if course.build.status != "ready":
        raise HTTPException(409, "Wait until the course map is ready, then add your notes.")
    repo = services.course(course.id)
    if len(repo.materials.list(student=uid)) >= MAX_MATERIALS:
        raise HTTPException(400, f"You can keep up to {MAX_MATERIALS} files per course. Remove one first.")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"{file.filename} is larger than {settings.max_upload_mb} MB")
    _allow_build(uid, "notes")  # reading and matching spends a few model calls
    concepts = [c for c in repo.concepts.list() if not c.removed]
    try:
        material = await run_in_threadpool(build_material, engine, concepts, uid, prereq_code, file.filename or "notes",
                                           data, guess_mime(file.filename or "", file.content_type))
    except UnsupportedFile as exc:
        raise HTTPException(415, str(exc)) from exc
    if repo.enrollments.get(uid) is None:
        repo.enrollments.put(Enrollment(id=uid))
    repo.materials.put(material)
    log.info("material %s for %s: %d parts, %d matches", material.id, course.id, len(material.chunks), len(material.matches))
    return _material_view(material, {c.id: c.name for c in concepts})


@app.delete("/api/courses/{course_id}/materials/{material_id}")
def delete_material(course_id: str, material_id: str, uid: str = Depends(current_uid)):
    repo = services.course(_course(course_id).id)
    m = repo.materials.get(material_id)
    if m is None or m.student != uid:
        raise HTTPException(404, "Not found")
    repo.materials.delete_many([m.id])
    return {"deleted": m.id}


@app.get("/api/courses/{course_id}/graph")
def course_graph(course_id: str, uid: str = Depends(current_uid)):
    """The prerequisite graph with this student's status on every concept."""
    course = _course(course_id)
    snap = _snapshot(course, uid)
    ids = list(snap.concepts)
    pairs = [(e.src, e.dst) for e in snap.edges]
    depth = depths(ids, pairs)
    nodes = []
    for cid, c in snap.concepts.items():
        view = concept_view(snap, c)
        nodes.append({**{k: view[k] for k in ("id", "name", "status", "p", "coverage", "covered_by", "foundation", "confidence", "next_need")},
                      "depth": depth.get(cid, 0)})
    return {
        "nodes": nodes,
        "edges": [{"src": e.src, "dst": e.dst, "confidence": e.confidence} for e in snap.edges],
        "needs": [{"concept_id": r.concept_id, "week": snap.topics[r.topic_id].week, "importance": r.importance}
                  for r in snap.requirements if r.topic_id in snap.topics],
        "weeks": sorted({t.week for t in snap.topics.values()}),
        "week_now": snap.week_now,
        "prereqs": sorted({c.covered_by for c in snap.concepts.values() if c.covered_by} | set(course.official_prereqs)),
    }


class AnswerBody(BaseModel):
    question_id: str
    choice: int
    phase: str = "check"


@app.post("/api/courses/{course_id}/answer")
def submit_answer(course_id: str, body: AnswerBody, uid: str = Depends(current_uid)):
    course = _course(course_id)
    repo = services.course(course.id)
    if repo.enrollments.get(uid) is None:
        repo.enrollments.put(Enrollment(id=uid))
    try:
        return answer(_snapshot(course, uid), repo, body.question_id, body.choice, body.phase)
    except NotFound:
        raise HTTPException(404, "Question not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/courses/{course_id}/concepts/{concept_id}")
def concept_study(course_id: str, concept_id: str, uid: str = Depends(current_uid)):
    course = _course(course_id)
    try:
        return study(_snapshot(course, uid), services.course(course.id), concept_id)
    except NotFound:
        raise HTTPException(404, "Concept not found")
@app.get("/api/courses/{course_id}/review")
def review(course_id: str, uid: str = Depends(current_uid)):
    course = _owned(course_id, uid)
    repo = services.course(course.id)
    names = {c.id: c.name for c in repo.concepts.list()}
    questions: dict[str, list] = {}
    for q in sorted(repo.questions.list(), key=lambda q: q.order):
        questions.setdefault(q.concept_id, []).append(q.model_dump(mode="json"))
    return {
        "concepts": [{**c.model_dump(mode="json"), "questions": questions.get(c.id, [])} for c in repo.concepts.list()],
        "flagged": sum(1 for qs in questions.values() for q in qs if q["verification"] == "disagreed" and q["status"] == "draft"),
        "edges": [{"src": names.get(e.src, "?"), "dst": names.get(e.dst, "?"), "confidence": e.confidence} for e in repo.edges.list()],
        "trace": [t.model_dump() for t in course.build.trace],
        "prereq_docs": [d.code for d in course.prereq_docs],
    }


class QuestionPatch(BaseModel):
    status: str | None = None
    prompt: str | None = None
    choices: list[str] | None = None
    correct_index: int | None = None
    explanation: str | None = None


@app.patch("/api/courses/{course_id}/questions/{question_id}")
def patch_question(course_id: str, question_id: str, body: QuestionPatch, uid: str = Depends(current_uid)):
    course = _owned(course_id, uid)
    repo = services.course(course.id)
    q = repo.questions.get(question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    edited = False
    if body.prompt is not None and body.prompt.strip():
        q.prompt, edited = body.prompt.strip(), True
    if body.choices is not None:
        if len(body.choices) != 4 or any(not c.strip() for c in body.choices):
            raise HTTPException(400, "Exactly 4 non-empty choices")
        q.choices, edited = [c.strip() for c in body.choices], True
    if body.correct_index is not None:
        if not 0 <= body.correct_index < 4:
            raise HTTPException(400, "correct_index must be 0-3")
        q.correct_index, edited = body.correct_index, True
    if body.explanation is not None:
        q.explanation, edited = body.explanation.strip(), True
    if edited:
        q.origin = "edited"
    if body.status in ("approved", "rejected", "draft"):
        q.status = body.status  # type: ignore[assignment]
    repo.questions.put(q)
    return q.model_dump(mode="json")


class ConceptPatch(BaseModel):
    removed: bool | None = None


@app.patch("/api/courses/{course_id}/concepts/{concept_id}")
def patch_concept(course_id: str, concept_id: str, body: ConceptPatch, uid: str = Depends(current_uid)):
    course = _owned(course_id, uid)
    repo = services.course(course.id)
    c = repo.concepts.get(concept_id)
    if c is None:
        raise HTTPException(404, "Concept not found")
    if body.removed is not None:
        c.removed = body.removed
    repo.concepts.put(c)
    return c.model_dump(mode="json")


def _revision_view(course_id: str, r: Revision) -> dict:
    repo = services.course(course_id)
    names = {c.id: c.name for c in repo.concepts.list()}
    weeks = {t.id: (t.week, t.title) for t in repo.topics.list()}
    return revise.view(r, names, weeks)


def _owned_revision(course_id: str, revision_id: str, uid: str) -> tuple[Course, Revision]:
    course = _owned(course_id, uid)
    r = services.course(course.id).revisions.get(revision_id)
    if r is None:
        raise HTTPException(404, "Revision not found")
    return course, r


@app.get("/api/courses/{course_id}/revisions")
def list_revisions(course_id: str, uid: str = Depends(current_uid)):
    """Requests to correct the map, newest first. Only the person who added the course sees them."""
    course = _owned(course_id, uid)
    found = sorted(services.course(course.id).revisions.list(), key=lambda r: r.created_at, reverse=True)
    return [_revision_view(course.id, r) for r in found[:20]]


@app.post("/api/courses/{course_id}/revisions")
async def ask_for_revision(course_id: str, prompt: str = Form(""), files: list[UploadFile] | None = File(None),
                           uid: str = Depends(account_uid)):
    """Ask for the map to be corrected: say what's wrong, and add files from the course that show it (a review guide,
    a study guide, sample exam or quiz questions). Changes are proposed for review; nothing changes until they're applied."""
    course = _owned(course_id, uid)
    if course.build.status != "ready":
        raise HTTPException(409, "Wait until the map is ready, then ask for changes.")
    uploads = files or []
    if len(uploads) > revise.MAX_FILES:
        raise HTTPException(400, f"Add up to {revise.MAX_FILES} files at a time.")
    if len(prompt.strip()) < 8 and not uploads:
        raise HTTPException(400, "Say what should change, add a file from the course, or both.")
    repo = services.course(course.id)
    if any(r.status in ("queued", "running") for r in repo.revisions.list()):
        raise HTTPException(409, "A request is already being worked on. Wait for it to finish.")
    _allow_build(uid)
    read = []
    for i, f in enumerate(uploads, start=1):
        data = await f.read()
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} is larger than {settings.max_upload_mb} MB")
        try:
            rf = await run_in_threadpool(revise.read_file, engine, f"f{i}", f.filename or f"file {i}", data,
                                         guess_mime(f.filename or "", f.content_type))
        except UnsupportedFile as exc:
            raise HTTPException(415, f"{f.filename}: {exc}") from exc
        if not rf.chunks:
            raise HTTPException(422, f"No text found in {f.filename}. If it's a scan, try a clearer photo or a PDF.")
        read.append(rf)
    r = Revision(owner=uid, prompt=prompt.strip()[:4000] or "Use the files to correct the map.", files=read)
    repo.revisions.put(r)
    _submit("revise", course.id, r.id)
    return _revision_view(course.id, r)


@app.get("/api/courses/{course_id}/revisions/{revision_id}")
def get_revision(course_id: str, revision_id: str, uid: str = Depends(current_uid)):
    course, r = _owned_revision(course_id, revision_id, uid)
    return _revision_view(course.id, r)


class ApplyBody(BaseModel):
    change_ids: list[str] = Field(default_factory=list, max_length=200)


@app.post("/api/courses/{course_id}/revisions/{revision_id}/apply")
def apply_revision(course_id: str, revision_id: str, body: ApplyBody, uid: str = Depends(current_uid)):
    """Apply the chosen changes to the map. Students' answers are kept."""
    course, r = _owned_revision(course_id, revision_id, uid)
    if r.status != "ready":
        raise HTTPException(409, "This request isn't waiting to be applied.")
    known = {ch.id for ch in r.changes}
    if not body.change_ids or not set(body.change_ids) <= known:
        raise HTTPException(400, "Choose at least one of the proposed changes.")
    result = revise.apply(services, course.id, r, body.change_ids)
    if result["added_concepts"] and services.course(course.id).prior_courses.list() + services.course(course.id).materials.list():
        _submit("students", course.id)  # students' own syllabi and notes are compared with the new concepts
    return {**result, "revision": _revision_view(course.id, r)}


@app.post("/api/courses/{course_id}/revisions/{revision_id}/discard")
def discard_revision(course_id: str, revision_id: str, uid: str = Depends(current_uid)):
    course, r = _owned_revision(course_id, revision_id, uid)
    if r.status not in ("ready", "error"):
        raise HTTPException(409, "Only a finished request can be discarded.")
    r.status = "discarded"
    services.course(course.id).revisions.put(r)
    return _revision_view(course.id, r)


class DeleteBody(BaseModel):
    confirm: str = Field(max_length=200)


@app.post("/api/courses/{course_id}/delete")
def delete_course(course_id: str, body: DeleteBody, uid: str = Depends(account_uid)):
    """Delete a course for everyone: its map, questions, students' answers, notes and earlier courses, and requests.
    The owner must type the course's number (or title) to confirm, as when deleting a repository."""
    course = _owned(course_id, uid)
    squash = lambda s: " ".join(s.split()).casefold()  # noqa: E731
    if squash(body.confirm) != squash(course.confirm_name):
        raise HTTPException(400, f"Type {course.confirm_name} exactly to confirm.")
    repo = services.course(course.id)
    if course.build.status in ("queued", "running") or any(r.status in ("queued", "running") for r in repo.revisions.list()):
        raise HTTPException(409, "The course is being mapped or revised right now. Delete it once that finishes.")
    with services.lock(course.id):
        students = sum(1 for e in repo.enrollments.list() if not e.simulated and e.id != uid)
        repo.wipe()
        services.catalog.courses.delete_many([course.id])
    log.info("course %s deleted by its owner (%d students)", course.id, students)
    return {"deleted": course.id, "students": students}


@app.post("/api/courses/{course_id}/recheck")
def recheck(course_id: str, uid: str = Depends(account_uid)):
    """Re-read the prerequisites (syllabus and Bulletin) and re-check what each one taught. Keeps the map and answers."""
    course = _owned(course_id, uid)
    if course.build.status != "ready":
        raise HTTPException(409, "Wait until the map is ready.")
    _allow_build(uid, "notes")
    course.build.stage = "Re-checking what prerequisites taught"
    services.catalog.put(course)
    _submit("recheck", course.id)
    return course.public()


@app.post("/api/courses/{course_id}/rebuild")
def rebuild(course_id: str, uid: str = Depends(account_uid)):
    course = _owned(course_id, uid)
    if course.demo:
        raise HTTPException(400, "The sample course is built from the hand-written library; add a real syllabus instead")
    _allow_build(uid)
    course.build.status, course.build.stage, course.build.error = "queued", "Queued", None
    services.catalog.put(course)
    _submit("build", course.id, course.code)
    return course.public()


@app.get("/api/courses/{course_id}/class")
def class_heatmap(course_id: str, include_simulated: bool = True, uid: str = Depends(current_uid)):
    course = _owned(course_id, uid)
    return class_view(course, services.course(course.id), services.now().date(), settings.min_cell, include_simulated)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    # Details go to the log; the user gets an id to quote, never internals.
    return JSONResponse({"detail": f"Something went wrong on our side (reference {request_id.get()})."}, status_code=500)
_static = settings.static_dir or os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")
if os.path.isdir(_static):
    if os.path.isdir(os.path.join(_static, "assets")):
        app.mount("/assets", StaticFiles(directory=os.path.join(_static, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = os.path.normpath(os.path.join(_static, path))
        if path and candidate.startswith(os.path.normpath(_static)) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_static, "index.html"))

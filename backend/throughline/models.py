"""Domain models.

A course map (timeline, prerequisite concepts, question bank) is built once per course and shared by
everyone in it. Each student owns only their enrollment settings and responses. The person who added
the course can see responses only as aggregates (see heatmap.py).
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

from .textutil import prereq_groups


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I


def new_join_code() -> str:
    return "".join(secrets.choice(_JOIN_ALPHABET) for _ in range(6))


Importance = Literal["essential", "helpful"]
QuestionStatus = Literal["draft", "approved", "rejected"]
Verification = Literal["agreed", "disagreed", "unverified"]
BuildStatus = Literal["queued", "running", "ready", "error"]
AiStance = Literal["encouraged", "limited", "prohibited", "unknown"]
# How the timeline was derived; shown to students so they know how much to trust the dates.
TimelineKind = Literal["dated_weeks", "weeks", "assessments", "estimated"]
Route = Literal["took_here", "equivalent", "permission", "unsure"]
SelfReport = Literal["yes", "never", "unsure"]
# How strongly the record says a listed prerequisite teaches a concept.
Coverage = Literal["listed", "likely", "missing", "unknown"]
# How a student met one listed prerequisite: took it, took an equivalent somewhere else, didn't take it, or isn't sure.
Met = Literal["took", "elsewhere", "none", "unsure"]


class StageTrace(BaseModel):
    """One pipeline stage as it actually ran: shown in the review tab and used by the evaluation harness."""

    stage: str
    ms: int = 0
    calls: dict[str, int] = Field(default_factory=dict)  # engine method -> number of model calls
    notes: list[str] = Field(default_factory=list)


class BuildState(BaseModel):
    status: BuildStatus = "queued"
    stage: str = ""
    done: int = 0
    total: int = 0
    error: str | None = None
    error_kind: str = ""  # syllabus | service | internal (see llm/failures.py)
    trace: list[StageTrace] = Field(default_factory=list)


class PrereqDoc(BaseModel):
    """A prerequisite course's syllabus, used as evidence of what that course actually taught."""

    code: str
    text: str  # redacted


class AiPolicy(BaseModel):
    stance: AiStance = "unknown"
    summary: str = ""


class Resource(BaseModel):
    title: str
    url: str | None = None
    detail: str = ""  # chapter/section, e.g. "Ch. 13: Linear Regression and Correlation"
    kind: Literal["syllabus", "open_textbook", "web"] = "open_textbook"


class BulletinEntry(BaseModel):
    code: str
    title: str = ""
    description: str = ""
    prerequisites: str = ""
    prereq_codes: list[str] = Field(default_factory=list)
    source: str = ""  # where it came from, e.g. "SF State Bulletin 2026-2027"

    def groups(self) -> list[list[str]]:
        return prereq_groups(self.prerequisites, self.prereq_codes)


class Course(BaseModel):
    id: str = Field(default_factory=lambda: new_id("crs"))
    owner: str
    code: str = ""
    title: str = ""
    term: str = ""
    term_start: dt.date | None = None
    term_end: dt.date | None = None
    official_prereqs: list[str] = Field(default_factory=list)  # course codes
    # The same codes as requirements: every group must be met; codes inside a group are alternatives ("A or B").
    prereq_groups: list[list[str]] = Field(default_factory=list)
    prereq_text: str = ""  # as written in the syllabus
    prereq_routes: list[str] = Field(default_factory=list)  # "or equivalent", "permission of the instructor", ...
    informal_requirements: list[str] = Field(default_factory=list)  # "Some programming experience is required"
    instructor_notes: list[str] = Field(default_factory=list)  # "You do not need linear algebra or calculus..."
    ai_policy: AiPolicy = Field(default_factory=AiPolicy)
    timeline_kind: TimelineKind = "weeks"
    resources: list[Resource] = Field(default_factory=list)  # free materials the syllabus itself recommends
    bulletin: list[BulletinEntry] = Field(default_factory=list)  # this course and its listed prerequisites
    prereq_docs: list[PrereqDoc] = Field(default_factory=list)  # never sent to clients
    join_code: str = Field(default_factory=new_join_code)
    published: bool = True
    demo: bool = False
    build: BuildState = Field(default_factory=BuildState)
    syllabus_text: str = ""  # redacted; never sent to clients
    created_at: datetime = Field(default_factory=utcnow)

    @field_serializer("prereq_groups")
    def _groups_out(self, groups: list[list[str]]) -> list[dict]:
        return [{"options": g} for g in groups]  # Firestore can't store a list inside a list

    @field_validator("prereq_groups", mode="before")
    @classmethod
    def _groups_in(cls, value):
        return [g["options"] if isinstance(g, dict) else g for g in value or []]

    @property
    def confirm_name(self) -> str:
        """What the owner types to delete the course: its number, else its title."""
        return self.code.strip() or self.title.strip() or "delete this course"

    def groups(self) -> list[list[str]]:
        """Courses mapped before groups were stored get them from the prerequisite statement."""
        return self.prereq_groups or prereq_groups(self.prereq_text, self.official_prereqs)

    def public(self) -> dict:
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "term": self.term,
            "term_start": self.term_start.isoformat() if self.term_start else None,
            "term_end": self.term_end.isoformat() if self.term_end else None,
            "official_prereqs": self.official_prereqs,
            "prereq_groups": self.groups(),
            "prereq_text": self.prereq_text,
            "prereq_routes": self.prereq_routes,
            "informal_requirements": self.informal_requirements,
            "instructor_notes": self.instructor_notes,
            "ai_policy": self.ai_policy.model_dump(),
            "timeline_kind": self.timeline_kind,
            "resources": [r.model_dump() for r in self.resources],
            "bulletin": [b.model_dump() for b in self.bulletin],
            "prereq_docs": [d.code for d in self.prereq_docs],
            "join_code": self.join_code,
            "demo": self.demo,
            "created_at": self.created_at.isoformat(),
            "build": self.build.model_dump(),
        }


class Topic(BaseModel):
    """One point on the course timeline: a week's lecture topic or a dated assessment."""

    id: str = Field(default_factory=lambda: new_id("tpc"))
    week: int
    date: dt.date | None = None
    title: str
    details: str = ""
    kind: Literal["lecture", "assessment"] = "lecture"
    estimated: bool = False  # date inferred, not stated in the syllabus


class Evidence(BaseModel):
    """A passage that supports (or fails to support) a coverage claim."""

    source: str  # e.g. "Bulletin: DS 212", "DS 212 syllabus, week 9", "This syllabus"
    quote: str
    verdict: Literal["teaches", "partial", "unrelated"] = "teaches"


class CourseCoverage(BaseModel):
    """What one listed prerequisite's record (its syllabus, or its Bulletin entry) says about a concept."""

    code: str
    coverage: Coverage = "unknown"  # missing = its syllabus was checked and doesn't have it
    source: str = ""  # e.g. "DS 212 syllabus", "Bulletin: DS 212 Business Statistics"
    quote: str = ""


class Concept(BaseModel):
    """Prior knowledge the course relies on before (or without) teaching it."""

    id: str = Field(default_factory=lambda: new_id("cpt"))
    name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    depth: str = ""  # how deep this course needs it, e.g. "interpret slope and R²; no derivations"
    foundation: bool = False  # not used by the course directly; needed for a concept that is
    confidence: float = 1.0  # share of independent mapping runs that proposed it
    covered_by: str | None = None  # listed prerequisite that teaches it, e.g. "DS 212"
    coverage: Coverage = "unknown"
    by_course: list[CourseCoverage] = Field(default_factory=list)  # the same question, per listed prerequisite
    hidden: bool = False  # coverage == "missing": needed, but no listed prerequisite teaches it
    evidence: str = ""  # one-line reason shown to students
    evidence_items: list[Evidence] = Field(default_factory=list)
    refresh_minutes: int = 20
    learn_minutes: int = 180
    refresher: str = ""  # short Markdown explanation for students who learned it before
    learn_outline: str = ""  # Markdown study path for students who never learned it
    resources: list[Resource] = Field(default_factory=list)
    removed: bool = False


class Edge(BaseModel):
    """src must be known before dst (src is a prerequisite of dst). Always acyclic within a course."""

    id: str = Field(default_factory=lambda: new_id("edg"))
    src: str
    dst: str
    confidence: float = 1.0


class Requirement(BaseModel):
    id: str = Field(default_factory=lambda: new_id("req"))
    topic_id: str
    concept_id: str
    importance: Importance = "essential"
    how_used: str = ""


class BankQuestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q"))
    concept_id: str
    prompt: str
    choices: list[str]
    correct_index: int
    explanation: str = ""
    status: QuestionStatus = "approved"
    verification: Verification = "unverified"
    verification_note: str = ""
    origin: Literal["ai", "sample", "edited", "instructor"] = "ai"  # instructor = from a file the course owner added
    order: int = 0

    def public(self) -> dict:
        """What a student sees before answering. The answer key never leaves the server."""
        return {"id": self.id, "concept_id": self.concept_id, "prompt": self.prompt, "choices": self.choices}


class Enrollment(BaseModel):
    """One student's settings for one course. Id is the student id, stored in the course partition."""

    id: str
    # Listed prerequisite code -> how this student met it. Alternatives are answered code by code, so a student
    # who took MATH 108 out of "DS 110 or MATH 108" has {"DS 110": "none", "MATH 108": "took"}.
    met: dict[str, Met] = Field(default_factory=dict)
    # Before `met`: one answer for the whole course, and the one alternative taken. Still read for older records.
    route: Route = "unsure"
    prereq_taken: str | None = None
    setup: bool = True  # False while only the prerequisite answers from the add-course form are saved
    weekly_minutes: int = 180
    self_report: dict[str, SelfReport] = Field(default_factory=dict)  # concept id -> studied before?
    simulated: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class MaterialChunk(BaseModel):
    loc: str  # "slide 14", "page 3", "section 2"
    text: str


class MaterialMatch(BaseModel):
    concept_id: str
    loc: str
    quote: str
    verdict: Literal["teaches", "partial"]


class Material(BaseModel):
    """A student's own notes, slides or handouts from a prerequisite course. Private to that student."""

    id: str = Field(default_factory=lambda: new_id("mat"))
    student: str
    prereq_code: str = ""
    filename: str
    kind: str = "notes"  # slides | pdf | notes | doc | photo
    chunks: list[MaterialChunk] = Field(default_factory=list)
    matches: list[MaterialMatch] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)


class PriorCourse(BaseModel):
    """A course the student took before this one, at any school, with its syllabus when they have it.

    It can stand in for a listed prerequisite ("I took CSE 206 instead of DS 212") or just be more background.
    Private to that student: its syllabus is evidence of what they were taught, nobody else's.
    """

    id: str = Field(default_factory=lambda: new_id("prc"))
    student: str
    code: str  # course number or short name, as the student wrote it
    title: str = ""
    school: str = ""  # empty = SF State
    replaces: str | None = None  # a listed prerequisite code it was taken instead of (or is that course itself)
    source: str = ""  # file name, or "pasted text"; empty when no syllabus was given
    chunks: list[MaterialChunk] = Field(default_factory=list)  # the syllabus, redacted and split into passages
    matches: list[MaterialMatch] = Field(default_factory=list)  # concepts it teaches, each with a verified quote
    checked: list[str] = Field(default_factory=list)  # concept ids compared with the syllabus (so "not found" means something)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def label(self) -> str:
        return f"{self.code} ({self.school})" if self.school else self.code


class RevisionFile(BaseModel):
    """A file the course owner added to a revision request: a review guide, study guide, sample exam..."""

    label: str  # "f1", "f2": how the model cites it
    filename: str
    kind: str = "notes"
    chunks: list[MaterialChunk] = Field(default_factory=list)  # redacted, with page or slide locations


ChangeKind = Literal["add_concept", "remove_concept", "edit_concept", "add_need", "remove_need", "add_question"]


class Change(BaseModel):
    """One proposed edit to the map, checked by code before the owner sees it."""

    id: str = Field(default_factory=lambda: new_id("chg"))
    kind: ChangeKind
    concept_id: str | None = None  # existing concept, or the new one's id for add_concept / its questions
    name: str = ""  # concept name, for display (and the new name for edit_concept)
    summary: str = ""
    depth: str = ""
    topic_id: str | None = None  # add_need / remove_need
    importance: Importance = "essential"
    how_used: str = ""
    reason: str = ""
    source: str = ""  # file name and location the quote is from; empty when it rests on the request alone
    quote: str = ""
    quote_ok: bool = False  # the quote really is in that file
    selected: bool = True  # proposed as on; the owner can switch any change off
    concept: Concept | None = None  # add_concept: the full concept, study material written
    needs: list[Requirement] = Field(default_factory=list)  # add_concept: where the course uses it
    builds_on: list[str] = Field(default_factory=list)  # add_concept: ids of concepts it builds on
    questions: list[BankQuestion] = Field(default_factory=list)  # add_question: one; add_concept: its study questions
    note: str = ""  # anything code changed or flagged, e.g. "the answer key was disputed: kept as a draft"


RevisionStatus = Literal["queued", "running", "ready", "applied", "discarded", "error"]


class Revision(BaseModel):
    """The course owner asking for the map to be corrected, with the files that back the request."""

    id: str = Field(default_factory=lambda: new_id("rev"))
    owner: str
    prompt: str
    files: list[RevisionFile] = Field(default_factory=list)
    status: RevisionStatus = "queued"
    stage: str = ""
    error: str = ""
    summary: str = ""  # the model's one-paragraph reading of the request
    not_done: list[str] = Field(default_factory=list)  # parts of the request it couldn't act on, and why
    changes: list[Change] = Field(default_factory=list)
    applied: list[str] = Field(default_factory=list)  # change ids applied
    calls: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    applied_at: datetime | None = None


class Response(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rsp"))
    student: str
    question_id: str
    concept_id: str
    choice: int
    correct: bool
    phase: Literal["check", "practice"] = "check"
    at: datetime = Field(default_factory=utcnow)
    simulated: bool = False

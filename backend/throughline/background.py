"""What one student brings to a course: which listed prerequisites they took, and earlier courses from anywhere.

A course can require several prerequisites ("CSC 317 and CSC 413") and accept alternatives ("DS 110 or MATH 108"),
and a student may have met any of them with a course at another school. So coverage is personal. For each concept:

  1. the student's own syllabi (any school) are checked first: a match there is the best evidence there is;
  2. then the shared record of each listed prerequisite the student says they took;
  3. otherwise we say why it isn't confirmed: a prerequisite teaches it but the student took another one, met it
     with a course whose syllabus doesn't show it, or didn't take it at all ("gap"), or nothing is known yet.

Until a student has said anything, they see the course-level answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ingest import syllabus_text
from .llm import Engine
from .materials import judge_passages
from .models import Concept, Course, CourseCoverage, Enrollment, Evidence, MaterialChunk, MaterialMatch, PriorCourse
from .retrieval import Passage, chunk_lines
from .textutil import course_code, redact

SYLLABUS_CHARS = 60_000  # per syllabus: a stored course record stays well under Firestore's 1 MB
MAX_PRIOR_COURSES = 8
# Priors: chance the student still knows a concept, before any answer or self-report (see mastery.py).
PRIOR_TAUGHT, PRIOR_OPEN, PRIOR_GAP = 0.55, 0.50, 0.35


def effective_met(enrollment: Enrollment, groups: list[list[str]]) -> dict[str, str]:
    """The student's answers for the listed prerequisites; older records had one answer for the whole course."""
    listed = [code for g in groups for code in g]
    if enrollment.met:
        return {code: how for code, how in enrollment.met.items() if code in listed}
    if enrollment.route == "equivalent":
        return {code: "elsewhere" for code in listed}
    if enrollment.route == "permission":
        return {code: "none" for code in listed}
    if enrollment.route != "took_here":
        return {}
    if enrollment.prereq_taken:  # the one alternative they picked; nothing was asked about the other requirements
        return {code: "took" if code == enrollment.prereq_taken else "none"
                for g in groups if enrollment.prereq_taken in g for code in g}
    return {g[0]: "took" for g in groups if len(g) == 1}


def unanswered_choices(course: Course, enrollment: Enrollment) -> list[list[str]]:
    """Requirements with alternatives ("A or B") the student hasn't answered: asked before the quick check."""
    groups = course.groups()
    met = effective_met(enrollment, groups)
    return [g for g in groups if len(g) > 1 and not any(code in met for code in g)]


def route_of(met: dict[str, str]) -> str:
    """The old one-word summary, kept on the record for the class view and older clients."""
    answers = set(met.values())
    for how, route in (("took", "took_here"), ("elsewhere", "equivalent"), ("none", "permission")):
        if how in answers:
            return route
    return "unsure"


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


@dataclass
class Personal:
    """One concept, for one student."""

    coverage: str  # listed | likely | missing | gap | unknown
    covered_by: str | None
    note: str
    prior: float = PRIOR_OPEN
    evidence: list[Evidence] = field(default_factory=list)  # quotes from the student's own syllabi


class Background:
    def __init__(self, course: Course, enrollment: Enrollment, prior_courses: list[PriorCourse]):
        self.groups = course.groups()
        self.met = effective_met(enrollment, self.groups)
        self.prior_courses = prior_courses
        self.given = bool(self.met) or bool(prior_courses)
        self.took = [code for g in self.groups for code in g if self.met.get(code) == "took"]
        # The student said they took none of the listed prerequisites here.
        self.away = bool(self.met) and not self.took and any(v in ("elsewhere", "none") for v in self.met.values())

    def _records(self, c: Concept) -> dict[str, CourseCoverage]:
        if c.by_course:
            return {r.code: r for r in c.by_course}
        if c.covered_by and c.coverage in ("listed", "likely"):  # mapped before coverage was kept per course
            first = c.evidence_items[0] if c.evidence_items else None
            return {c.covered_by: CourseCoverage(code=c.covered_by, coverage=c.coverage, source=first.source if first else "",
                                                 quote=first.quote if first else "")}
        return {}

    def _requirement(self, group: list[str], c: Concept, records: dict[str, CourseCoverage]) -> tuple[str, str]:
        """How the student met one requirement, given that none of their courses shows the concept:
        ("no", why) they can't have got it there; ("unknown", why) can't tell; ("open", "") they haven't said."""
        took = [code for code in group if self.met.get(code) == "took"]
        answers = {self.met[code] for code in group if code in self.met}
        if took:
            for code in took:
                own = [p for p in self.prior_courses if course_code(p.code) == code and not p.school]
                if any(c.id in p.checked for p in own) or (code in records and records[code].coverage == "missing"):
                    continue
                return "unknown", f"{code}, which you took, isn't confirmed to cover it"
            return "no", f"it isn't in the {_join(took)} syllabus"
        if "elsewhere" in answers:
            subs = [p for p in self.prior_courses if p.replaces in group]
            if subs and all(c.id in p.checked for p in subs):
                return "no", f"it isn't in your {_join([p.label for p in subs])} syllabus"
            return "unknown", "add the syllabus of the course you took instead to check"
        if answers == {"none"}:
            return "no", "you didn't take it"
        return "open", ""

    def of(self, c: Concept) -> Personal:
        own = sorted(((p, m) for p in self.prior_courses for m in p.matches if m.concept_id == c.id),
                     key=lambda pm: pm[1].verdict != "teaches")
        if own:
            p, m = own[0]
            taught = m.verdict == "teaches"
            return Personal("listed" if taught else "likely", p.label, f"Your {p.label} syllabus: “{m.quote}”",
                            PRIOR_TAUGHT if taught else PRIOR_OPEN,
                            [Evidence(source=f"Your {q.label} syllabus", quote=x.quote, verdict=x.verdict) for q, x in own[:3]])

        records = self._records(c)
        mine = sorted((records[code] for code in self.took if code in records and records[code].coverage in ("listed", "likely")),
                      key=lambda r: r.coverage != "listed")
        if mine:
            r = mine[0]
            note = f"{r.source}: “{r.quote}”" if r.quote else f"Usually taught in {r.code}; its Bulletin description doesn't confirm it."
            return Personal(r.coverage, r.code, note, PRIOR_TAUGHT if r.coverage == "listed" else PRIOR_OPEN)

        shared = Personal(c.coverage, c.covered_by, c.evidence, PRIOR_GAP if c.coverage == "missing" else PRIOR_OPEN)
        if not self.given:
            return shared
        teachers = [r.code for r in records.values() if r.coverage in ("listed", "likely")]
        absent = [p.label for p in self.prior_courses if c.id in p.checked]
        also = f" It isn't in your {_join(absent)} syllabus either." if absent else ""
        if c.coverage == "missing" and not teachers:
            return Personal("missing", None, c.evidence + also, PRIOR_GAP)

        if teachers:
            groups = [g for g in self.groups if any(t in g for t in teachers)]
            views = [self._requirement(g, c, records) for g in groups]
            lead = f"{_join(teachers)} {'teaches' if len(teachers) == 1 else 'teach'} it"
            if not views or any(state == "open" for state, _ in views):
                return shared
            if all(state == "no" for state, _ in views):
                return Personal("gap", None, f"{lead}, but {views[0][1]}.", PRIOR_GAP)
            why = next(reason for state, reason in views if state == "unknown")
            return Personal("unknown", None, f"{lead}; {why}.", PRIOR_OPEN)

        views = [self._requirement(g, c, records) for g in self.groups]
        if views and all(state == "no" for state, _ in views):
            reasons = list(dict.fromkeys(reason for _, reason in views))
            return Personal("gap", None, "No course you took shows it: " + "; ".join(reasons) + ".", PRIOR_GAP)
        return Personal("unknown", None, c.evidence + also, PRIOR_GAP if self.away else PRIOR_OPEN)


# ---------- the student's own syllabi ----------

def syllabus_chunks(text: str) -> list[MaterialChunk]:
    """Redact, then split into schedule-row-sized passages so a quote points at one week."""
    return [MaterialChunk(loc=f"part {i}", text=t) for i, t in enumerate(chunk_lines(redact(text)[:SYLLABUS_CHARS]), start=1)]


def read_syllabus(engine: Engine, data: bytes | None, filename: str, mime: str, pasted: str) -> tuple[str, list[MaterialChunk]]:
    """(source label, passages) from an uploaded file or pasted text; ("", []) when neither was given."""
    if data:
        return (filename or "syllabus")[:120], syllabus_chunks(syllabus_text(engine, data, filename, mime))
    if pasted.strip():
        return "pasted text", syllabus_chunks(pasted)
    return "", []


def match_prior_course(engine: Engine, concepts: list[Concept], prior: PriorCourse) -> None:
    """Find which of the course's concepts this syllabus teaches. Records what was compared, so that a concept
    with no match can be reported as "not in your syllabus" rather than "not checked"."""
    prior.matches, prior.checked = [], []
    if not concepts or not prior.chunks:
        return
    passages = [Passage(label=f"s{i}", source=f"{prior.label} syllabus", text=ch.text, kind="prior_syllabus", code=None)
                for i, ch in enumerate(prior.chunks)]
    loc_of = {p.label: ch.loc for p, ch in zip(passages, prior.chunks)}
    found, judged = judge_passages(engine, concepts, passages)
    prior.matches = [MaterialMatch(concept_id=cid, loc=loc_of[p.label], quote=quote, verdict=verdict) for cid, p, quote, verdict in found]
    prior.checked = sorted(judged)


def view(prior: PriorCourse, names: dict[str, str]) -> dict:
    """What the student sees of one of their earlier courses. The syllabus text itself is never sent back."""
    covers = {}
    for m in prior.matches:
        if m.concept_id in names:
            covers.setdefault(m.concept_id, {"concept_id": m.concept_id, "name": names[m.concept_id], "quote": m.quote, "verdict": m.verdict})
    return {"id": prior.id, "code": prior.code, "title": prior.title, "school": prior.school, "replaces": prior.replaces,
            "source": prior.source, "has_syllabus": bool(prior.chunks), "checked": sum(1 for cid in prior.checked if cid in names),
            "covers": list(covers.values()), "created_at": prior.created_at.isoformat()}

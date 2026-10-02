"""The course timeline and a student's pace plan.

The plan is computed, not generated. Every concept the coming classes need and the student doesn't know
yet becomes a task; so do the foundations of anything they must refresh or learn. Deadlines are pulled
earlier along the prerequisite graph (a foundation is due early enough to leave time for what builds on
it: d'(u) = min(d(u), d'(v) - time(v)) for every edge u -> v), then tasks are scheduled earliest-adjusted-
deadline-first into the student's weekly time budget, starting with what's left of this week. Whatever
can't be finished in time is reported as at risk, with the shortfall in minutes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import cached_property

from . import mastery as mx
from .graph import topological_order
from .materials import KIND_WORD
from .models import Concept, Course, Edge, Enrollment, Material, Requirement, Response, Topic
from .repo import CourseRepo

CHECK_MINUTES = 3
CONFIRM_MINUTES = 3
HORIZON_WEEKS = 3


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def current_week(course: Course, topics: list[Topic], today: date) -> int:
    start = course.term_start
    if start is None:
        dated = sorted((t for t in topics if t.date), key=lambda t: t.date)  # type: ignore[arg-type, return-value]
        if dated:
            start = monday(dated[0].date) - timedelta(weeks=dated[0].week - 1)  # type: ignore[arg-type]
    if start is None:
        return 1
    return (today - start).days // 7 + 1


def topic_date(course: Course, topic: Topic, today: date, week_now: int) -> date:
    if topic.date:
        return topic.date
    if course.term_start:
        return course.term_start + timedelta(weeks=topic.week - 1)
    return monday(today) + timedelta(weeks=topic.week - week_now)


@dataclass
class Need:
    topic: Topic
    importance: str
    how_used: str
    overdue: bool
    via: str | None = None  # name of the dependent concept, when this is a foundation


@dataclass
class Snapshot:
    course: Course
    topics: dict[str, Topic]
    concepts: dict[str, Concept]
    requirements: list[Requirement]
    edges: list[Edge]
    responses: list[Response]
    enrollment: Enrollment
    today: date
    materials: list[Material] = field(default_factory=list)  # this student's own notes and slides

    @classmethod
    def load(cls, course: Course, repo: CourseRepo, student: str, today: date) -> "Snapshot":
        concepts = {c.id: c for c in repo.concepts.list() if not c.removed}
        return cls(
            course=course,
            topics={t.id: t for t in repo.topics.list()},
            concepts=concepts,
            requirements=[r for r in repo.requirements.list() if r.concept_id in concepts],
            edges=[e for e in repo.edges.list() if e.src in concepts and e.dst in concepts],
            responses=repo.responses.list(student=student),
            enrollment=repo.enrollments.get(student) or Enrollment(id=student),
            today=today,
            materials=repo.materials.list(student=student),
        )
    @cached_property
    def notes(self) -> dict[str, list[dict]]:
        """concept id -> where this student's own materials cover it, best first."""
        out: dict[str, list[dict]] = {}
        for m in self.materials:
            label = f"{m.prereq_code} {KIND_WORD.get(m.kind, 'notes')}".strip() if m.prereq_code else KIND_WORD.get(m.kind, "notes")
            for x in m.matches:
                if x.concept_id in self.concepts:
                    out.setdefault(x.concept_id, []).append({"material_id": m.id, "file": m.filename, "label": label,
                                                             "loc": x.loc, "quote": x.quote, "verdict": x.verdict})
        for hits in out.values():
            hits.sort(key=lambda h: h["verdict"] != "teaches")
        return out

    def where_to_learn(self, c: Concept, limit: int = 3) -> list[dict]:
        """Concrete places to study a concept: the student's own notes first, then the best free resources."""
        items = [{"kind": "notes", "title": f"Your {h['label']}: {h['file']}", "detail": h["loc"], "url": None, "quote": h["quote"]}
                 for h in self.notes.get(c.id, [])[:2]]
        for r in c.resources:
            if len(items) >= limit:
                break
            items.append({"kind": r.kind, "title": r.title, "detail": r.detail, "url": r.url, "quote": ""})
        return items
    @cached_property
    def model(self) -> mx.KnowledgeModel:
        return mx.KnowledgeModel.build(list(self.concepts.values()), self.edges, self.enrollment, self.responses,
                                       in_notes=set(self.notes))

    @cached_property
    def states(self) -> dict[str, mx.ConceptState]:
        return mx.assess(self.model, list(self.concepts.values()), self.enrollment, {c.id: c.name for c in self.concepts.values()},
                         notes={cid: hits[0]["label"] for cid, hits in self.notes.items()})

    def refresh(self) -> None:
        """Forget cached inference after a new response."""
        for key in ("model", "states"):
            self.__dict__.pop(key, None)

    def status(self, concept_id: str) -> mx.Status:
        return self.states[concept_id].status
    @cached_property
    def week_now(self) -> int:
        return current_week(self.course, list(self.topics.values()), self.today)

    def when(self, topic: Topic) -> date:
        return topic_date(self.course, topic, self.today, self.week_now)

    def upcoming(self, topic: Topic) -> bool:
        """Exactly dated items are past once their day is; week-level items stay current for the whole week."""
        if topic.date is not None and not topic.estimated:
            return topic.date >= self.today
        return topic.week >= self.week_now

    def due(self, topic: Topic) -> date:
        return max(self.when(topic), self.today)
    @cached_property
    def dependents(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for e in self.edges:
            out.setdefault(e.src, []).append(e.dst)
        return out

    @cached_property
    def foundations(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for e in self.edges:
            out.setdefault(e.dst, []).append(e.src)
        return out

    def needs(self, concept_id: str) -> list[tuple[Topic, Requirement]]:
        pairs = [(self.topics[r.topic_id], r) for r in self.requirements if r.concept_id == concept_id and r.topic_id in self.topics]
        return sorted(pairs, key=lambda p: (self.when(p[0]), p[0].week))

    def next_need(self, concept_id: str, _seen: frozenset = frozenset()) -> Need | None:
        """The next class that needs this concept, directly or through something that builds on it."""
        pairs = self.needs(concept_id)
        if pairs:
            upcoming = [p for p in pairs if self.upcoming(p[0])]
            t, r = upcoming[0] if upcoming else pairs[-1]
            return Need(t, r.importance, r.how_used, overdue=not upcoming)
        best: Need | None = None
        for dep in self.dependents.get(concept_id, []):
            if dep in _seen:
                continue
            n = self.next_need(dep, _seen | {concept_id})
            if n and (best is None or (n.overdue, self.when(n.topic)) < (best.overdue, self.when(best.topic))):
                best = Need(n.topic, n.importance, f"{self.concepts[concept_id].name} is a foundation for {self.concepts[dep].name}.",
                            n.overdue, via=self.concepts[dep].name)
        return best

    def effort(self, concept: Concept, status: str) -> int:
        if status == "learn":
            return concept.learn_minutes
        if status == "refresh":
            return concept.refresh_minutes
        if status == "likely":
            return CONFIRM_MINUTES
        return CHECK_MINUTES


def concept_view(snap: Snapshot, c: Concept) -> dict:
    s = snap.states[c.id]
    nxt = snap.next_need(c.id)
    coverage, covered_by = c.coverage, c.covered_by
    if coverage in ("listed", "likely") and not mx.coverage_applies(c, snap.enrollment):
        coverage, covered_by = "unknown", None  # taught in an alternative prerequisite, not the one this student took
    return {
        "id": c.id,
        "name": c.name,
        "summary": c.summary,
        "depth": c.depth,
        "foundation": c.foundation,
        "confidence": c.confidence,
        "covered_by": covered_by,
        "coverage": coverage,
        "hidden": c.hidden,
        "in_your_notes": snap.notes.get(c.id, [])[:3],
        "status": s.status,
        "status_label": mx.LABEL[s.status],
        "p": s.p,
        "basis": s.basis,
        "self_report": snap.enrollment.self_report.get(c.id),
        "correct": s.correct,
        "attempts": s.attempts,
        "builds_on": [snap.concepts[f].name for f in snap.foundations.get(c.id, [])],
        "next_need": None if nxt is None else {
            "week": nxt.topic.week, "date": snap.when(nxt.topic).isoformat(), "title": nxt.topic.title,
            "how_used": nxt.how_used, "importance": nxt.importance, "overdue": nxt.overdue, "via": nxt.via,
        },
        "minutes": snap.effort(c, s.status) if s.status != "ready" else 0,
    }


def timeline(snap: Snapshot, horizon: int | None = None) -> list[dict]:
    week_now = snap.week_now
    out = []
    for t in sorted(snap.topics.values(), key=lambda t: (t.week, snap.when(t))):
        if horizon is not None and not (week_now <= t.week < week_now + horizon):
            continue
        reqs = [r for r in snap.requirements if r.topic_id == t.id]
        out.append({
            "id": t.id, "week": t.week, "date": snap.when(t).isoformat(), "date_stated": t.date is not None and not t.estimated,
            "title": t.title, "details": t.details, "kind": t.kind, "estimated": t.estimated,
            "past": not snap.upcoming(t),
            "requires": [{"concept_id": r.concept_id, "name": snap.concepts[r.concept_id].name, "importance": r.importance,
                          "how_used": r.how_used, "status": snap.status(r.concept_id)} for r in reqs],
        })
    return out


def plan(snap: Snapshot) -> dict:
    budget = max(15, snap.enrollment.weekly_minutes)
    per_day = budget / 7
    today = snap.today

    # 1. Tasks: needed concepts that aren't ready, plus foundations of anything to refresh or learn.
    tasks: dict[str, dict] = {}

    def add(cid: str) -> None:
        if cid in tasks:
            return
        c, st = snap.concepts[cid], snap.status(cid)
        need = snap.next_need(cid)
        if st == "ready" or need is None:
            return
        tasks[cid] = {"concept": c, "status": st, "minutes": snap.effort(c, st), "need": need,
                      "due": today if need.overdue else snap.due(need.topic)}
        if st in ("learn", "refresh"):
            for f in snap.foundations.get(cid, []):
                add(f)

    for cid in snap.concepts:
        if snap.needs(cid) or snap.status(cid) in ("learn", "refresh"):
            add(cid)

    # 2. Precedence-adjusted deadlines, processed from the last concept in the graph backwards.
    ids = list(tasks)
    edges = [(e.src, e.dst) for e in snap.edges if e.src in tasks and e.dst in tasks]
    order = topological_order(ids, edges)
    rank = {cid: i for i, cid in enumerate(order)}
    adjusted = {cid: tasks[cid]["due"] for cid in ids}
    pulled_by: dict[str, str] = {}  # the dependent whose own deadline moved this one earlier
    for cid in reversed(order):
        for dep in snap.dependents.get(cid, []):
            if dep in tasks:
                lead = timedelta(days=math.ceil(tasks[dep]["minutes"] / per_day))
                if adjusted[dep] - lead < adjusted[cid]:
                    adjusted[cid] = adjusted[dep] - lead
                    pulled_by[cid] = dep
    for cid in ids:
        adjusted[cid] = max(adjusted[cid], today)
        tasks[cid]["deadline"] = adjusted[cid]
        tasks[cid]["before"] = snap.concepts[pulled_by[cid]].name if cid in pulled_by else None

    items = sorted(tasks.values(), key=lambda t: (t["deadline"], rank[t["concept"].id], not t["need"].overdue,
                                                  t["need"].importance != "essential", t["concept"].name))

    # 3. Fill weekly budgets earliest-deadline-first; this week is prorated to the days left.
    days_left = 7 - today.weekday()
    weeks: list[dict] = []
    remaining: list[int] = []
    last = max((t["deadline"] for t in items), default=today)
    w_start = monday(today)
    while w_start <= last or not weeks:
        cap = round(budget * days_left / 7) if not weeks else budget
        weeks.append({"start": w_start.isoformat(), "end": (w_start + timedelta(days=6)).isoformat(), "capacity": cap, "items": []})
        remaining.append(cap)
        w_start += timedelta(weeks=1)

    at_risk = []
    for it in items:
        need = it["minutes"]
        for wi, wk in enumerate(weeks):
            if need <= 0:
                break
            # Study has to happen before the class: a later week counts only if it starts before the deadline.
            if date.fromisoformat(wk["start"]) >= it["deadline"] and wi > 0:
                break
            take = min(need, remaining[wi])
            if take <= 0:
                continue
            remaining[wi] -= take
            need -= take
            wk["items"].append(_plan_item(snap, it, take, partial=take < it["minutes"]))
        if need > 0:
            at_risk.append({**_plan_item(snap, it, it["minutes"], partial=False), "short_by": need})

    for wk, rem in zip(weeks, remaining):
        wk["minutes"] = wk["capacity"] - rem
    counts = {k: sum(1 for t in items if t["status"] == k) for k in ("learn", "refresh", "unchecked", "likely")}
    return {
        "today": today.isoformat(),
        "week_now": snap.week_now,
        "weekly_minutes": budget,
        "total_minutes": sum(t["minutes"] for t in items),
        "counts": {
            "ready": sum(1 for c in snap.concepts if snap.status(c) == "ready"),
            "to_do": len(items),
            **counts,
            "foundations": sum(1 for t in items if t["need"].via),
            "overdue": sum(1 for t in items if t["need"].overdue),
        },
        "weeks": [w for w in weeks if w["items"]],
        "at_risk": at_risk,
    }


def _plan_item(snap: Snapshot, it: dict, minutes: int, partial: bool) -> dict:
    c, need = it["concept"], it["need"]
    return {
        "concept_id": c.id,
        "name": c.name,
        "status": it["status"],
        "status_label": mx.LABEL[it["status"]],
        "minutes": minutes,
        "total_minutes": it["minutes"],
        "partial": partial,
        "due": it["due"].isoformat(),
        "do_by": it["deadline"].isoformat(),
        "overdue": need.overdue,
        "for_week": need.topic.week,
        "for_title": need.topic.title,
        "for_kind": need.topic.kind,
        "foundation_for": need.via,
        "before": it["before"],
        "importance": need.importance,
        "coverage": c.coverage,
        "hidden": c.hidden,
        "study": snap.where_to_learn(c),
    }

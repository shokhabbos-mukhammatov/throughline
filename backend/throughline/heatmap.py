"""Class view for whoever added the course: aggregates only, never individual students.

A concept's numbers are shown only once at least `min_cell` students have answered or reported on it
(k-anonymity), so no one student's result can be read off the screen.
"""

from __future__ import annotations

from datetime import date

from . import mastery as mx
from .models import Course
from .readiness import HORIZON_WEEKS, current_week, topic_date
from .repo import CourseRepo


def class_view(course: Course, repo: CourseRepo, today: date, min_cell: int, include_simulated: bool = True) -> dict:
    topics = {t.id: t for t in repo.topics.list()}
    concepts = {c.id: c for c in repo.concepts.list() if not c.removed}
    clist = list(concepts.values())
    edges = [e for e in repo.edges.list() if e.src in concepts and e.dst in concepts]
    names = {c.id: c.name for c in clist}
    reqs = [r for r in repo.requirements.list() if r.concept_id in concepts and r.topic_id in topics]
    enrollments = {e.id: e for e in repo.enrollments.list() if include_simulated or not e.simulated}
    responses = [r for r in repo.responses.list() if r.student in enrollments]
    week_now = current_week(course, list(topics.values()), today)

    per_student: dict[str, dict[str, list]] = {}
    all_by_student: dict[str, list] = {}
    for r in sorted(responses, key=lambda r: r.at):
        per_student.setdefault(r.student, {}).setdefault(r.concept_id, []).append(r)
        all_by_student.setdefault(r.student, []).append(r)
    # Same knowledge model the student sees, one per student; only totals leave this function.
    statuses = {
        sid: mx.assess(mx.KnowledgeModel.build(clist, edges, e, all_by_student.get(sid, [])), clist, e, names)
        for sid, e in enrollments.items()
    }

    rows = []
    for c in concepts.values():
        weeks = sorted({topics[r.topic_id].week for r in reqs if r.concept_id == c.id})
        if not weeks:
            continue  # foundations appear through the concepts they support
        first_try = never = ready = n = 0
        for sid, e in enrollments.items():
            rs = per_student.get(sid, {}).get(c.id, [])
            report = e.self_report.get(c.id)
            if not rs and report is None:
                continue
            n += 1
            if rs and rs[0].correct:
                first_try += 1
            if report == "never":
                never += 1
            if statuses[sid][c.id].status == "ready":
                ready += 1
        answered = sum(1 for sid in enrollments if per_student.get(sid, {}).get(c.id))
        shown = n >= min_cell
        upcoming = [w for w in weeks if week_now <= w < week_now + HORIZON_WEEKS]
        first_week = upcoming[0] if upcoming else weeks[0]
        first_topic = min((topics[r.topic_id] for r in reqs if r.concept_id == c.id and topics[r.topic_id].week == first_week),
                          key=lambda t: t.week)
        rows.append({
            "concept_id": c.id,
            "name": c.name,
            "covered_by": c.covered_by,
            "coverage": c.coverage,
            "hidden": c.hidden,
            "weeks": weeks,
            "first_week": first_week,
            "first_date": topic_date(course, first_topic, today, week_now).isoformat(),
            "first_title": first_topic.title,
            "upcoming": bool(upcoming),
            "n": n,
            "suppressed": not shown,
            "first_try": round(first_try / answered, 3) if shown and answered else None,
            "never": round(never / n, 3) if shown and n else None,
            "ready": round(ready / n, 3) if shown and n else None,
        })
    rows.sort(key=lambda r: (not r["upcoming"], r["first_week"], r["name"]))

    concerns = [r for r in rows if r["upcoming"] and not r["suppressed"] and
                ((r["first_try"] is not None and r["first_try"] < 0.6) or (r["never"] or 0) >= 0.25)]
    concerns.sort(key=lambda r: (r["first_week"], -(r["never"] or 0), r["first_try"] if r["first_try"] is not None else 1))
    sim = sum(1 for e in enrollments.values() if e.simulated)
    return {
        "week_now": week_now,
        "weeks": sorted({t.week for t in topics.values()}),
        "students": len(enrollments),
        "simulated": sim,
        "min_cell": min_cell,
        "rows": rows,
        "concerns": concerns[:5],
    }

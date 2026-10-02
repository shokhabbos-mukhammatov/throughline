"""Adaptive checks and practice over a course's question bank.

The quick check asks one question at a time. Each next question is the one with the largest expected
information gain about the concepts the student needs in the next few weeks (and their foundations),
given every answer so far (see mastery.py). It stops when no question would tell us much, or after
MAX_QUESTIONS. All questions are multiple choice, graded by code against a key that never leaves the server.
"""

from __future__ import annotations

from . import mastery as mx
from .models import BankQuestion, Response
from .readiness import HORIZON_WEEKS, Snapshot, concept_view
from .repo import CourseRepo

MAX_QUESTIONS = 8


class NotFound(KeyError):
    pass


def _bank(repo: CourseRepo) -> dict[str, list[BankQuestion]]:
    out: dict[str, list[BankQuestion]] = {}
    for q in sorted(repo.questions.list(status="approved"), key=lambda q: q.order):
        out.setdefault(q.concept_id, []).append(q)
    return out


def next_question(snap: Snapshot, bank: dict[str, list[BankQuestion]], concept_id: str) -> BankQuestion | None:
    """The first question this student hasn't answered; if all are used, the one answered longest ago."""
    pool = bank.get(concept_id, [])
    if not pool:
        return None
    answered = {r.question_id: r.at for r in snap.responses if r.concept_id == concept_id}
    fresh = [q for q in pool if q.id not in answered]
    if fresh:
        return fresh[0]
    return min(pool, key=lambda q: answered[q.id])


def focus_concepts(snap: Snapshot) -> list[str]:
    """Concepts needed within the horizon (or overdue), plus their foundations."""
    week_now = max(snap.week_now, 1)
    focus: list[str] = []
    for cid in snap.concepts:
        need = snap.next_need(cid)
        if need and (need.overdue or need.topic.week < week_now + HORIZON_WEEKS):
            focus.append(cid)
    stack = list(focus)
    while stack:
        for f in snap.foundations.get(stack.pop(), []):
            if f not in focus:
                focus.append(f)
                stack.append(f)
    return focus


def _reason(snap: Snapshot, cid: str, session: list[Response]) -> str:
    name = snap.concepts[cid].name
    last = session[-1] if session else None
    if last and last.concept_id != cid:
        prev = snap.concepts.get(last.concept_id)
        if prev:
            if not last.correct and cid in snap.foundations.get(last.concept_id, []):
                return f"You missed {prev.name}, so this checks its foundation, {name}."
            if last.correct and last.concept_id in snap.foundations.get(cid, []):
                return f"You got {prev.name}; this checks {name}, which builds on it."
    need = snap.next_need(cid)
    if need is None:
        return f"Checking {name}."
    where = f"week {need.topic.week}: {need.topic.title}"
    if need.via:
        return f"{name} is a foundation for {need.via}, which " + ("is already in use" if need.overdue else "is needed") + f" ({where})."
    if need.overdue:
        return f"{name} is already in use ({where})."
    return f"{name} is needed for {where}."


def adaptive_next(snap: Snapshot, repo: CourseRepo, session_ids: list[str]) -> dict:
    """Pick the most informative next question, or report that the check is done."""
    session = [r for r in snap.responses if r.id in set(session_ids)]
    bank = _bank(repo)
    focus = focus_concepts(snap)
    model = snap.model
    index = {cid: i for i, cid in enumerate(model.ids)}
    focus_idx = [index[c] for c in focus if c in index]
    asked_now: dict[str, int] = {}
    for r in session:
        asked_now[r.concept_id] = asked_now.get(r.concept_id, 0) + 1

    best: tuple[float, str] | None = None
    if len(session) < MAX_QUESTIONS:
        for cid in focus:
            if cid not in bank or asked_now.get(cid, 0) >= 2:
                continue
            if snap.enrollment.self_report.get(cid) == "never" and not any(r.concept_id == cid for r in snap.responses):
                continue  # straight to Learn: quizzing what they've never studied wastes their time
            gain = model.expected_gain(index[cid], focus_idx)
            if best is None or gain > best[0] + 1e-9:
                best = (gain, cid)

    summary = [concept_view(snap, snap.concepts[c]) for c in focus]
    if best is None or best[0] < mx.MIN_GAIN:
        return {"done": True, "asked": len(session), "focus": summary}
    gain, cid = best
    q = next_question(snap, bank, cid)
    if q is None:
        return {"done": True, "asked": len(session), "focus": summary}
    return {
        "done": False,
        "asked": len(session),
        "max_questions": MAX_QUESTIONS,
        "question": {**q.public(), "concept_name": snap.concepts[cid].name},
        "reason": _reason(snap, cid, session),
        "gain_bits": round(gain, 3),
        "focus": summary,
    }


def answer(snap: Snapshot, repo: CourseRepo, question_id: str, choice: int, phase: str) -> dict:
    q = repo.questions.get(question_id)
    if q is None or q.status != "approved" or q.concept_id not in snap.concepts:
        raise NotFound(question_id)
    if not 0 <= choice < len(q.choices):
        raise ValueError("choice out of range")
    before = {cid: (s.status, s.p) for cid, s in snap.states.items()}
    r = Response(student=snap.enrollment.id, question_id=q.id, concept_id=q.concept_id, choice=choice,
                 correct=choice == q.correct_index, phase="practice" if phase == "practice" else "check")
    repo.responses.put(r)
    snap.responses.append(r)
    snap.refresh()
    after = snap.states
    s = after[q.concept_id]
    changed = [
        {"concept_id": cid, "name": snap.concepts[cid].name, "p_before": before[cid][1], "p_after": st.p,
         "status_before": before[cid][0], "status_after": st.status}
        for cid, st in after.items()
        if cid != q.concept_id and abs(st.p - before[cid][1]) >= 0.05
    ]
    return {
        "response_id": r.id,
        "question_id": q.id,
        "concept_id": q.concept_id,
        "correct": r.correct,
        "correct_index": q.correct_index,
        "explanation": q.explanation,
        "status_before": before[q.concept_id][0],
        "status_after": s.status,
        "status_label": mx.LABEL[s.status],
        "p_before": before[q.concept_id][1],
        "p_after": s.p,
        "basis": s.basis,
        "correct_count": s.correct,
        "attempts": s.attempts,
        "also_changed": sorted(changed, key=lambda x: -abs(x["p_after"] - x["p_before"]))[:4],
    }


def study(snap: Snapshot, repo: CourseRepo, concept_id: str) -> dict:
    c = snap.concepts.get(concept_id)
    if c is None:
        raise NotFound(concept_id)
    q = next_question(snap, _bank(repo), concept_id)
    uses = [{"week": t.week, "date": snap.when(t).isoformat(), "title": t.title, "kind": t.kind, "how_used": r.how_used,
             "importance": r.importance, "past": not snap.upcoming(t)} for t, r in snap.needs(concept_id)]
    return {
        **concept_view(snap, c),
        "evidence": c.evidence,
        "evidence_items": [e.model_dump() for e in c.evidence_items],
        "aliases": c.aliases,
        "leads_to": [snap.concepts[d].name for d in snap.dependents.get(concept_id, [])],
        "refresher": c.refresher,
        "learn_outline": c.learn_outline,
        "refresh_minutes": c.refresh_minutes,
        "learn_minutes": c.learn_minutes,
        "resources": [r.model_dump() for r in c.resources],
        "where_to_learn": snap.where_to_learn(c, limit=4),
        "uses": uses,
        "practice": q.public() if q else None,
    }

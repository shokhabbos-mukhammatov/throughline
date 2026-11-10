"""Correcting a map after it is built: the course owner's request, backed by files from the course.

The AI drafts a map from the syllabus, so it can be wrong. The person who added the course writes what is wrong ("Week 6
doesn't use logarithms", "they assume Bayes' rule") and can add the files that show it: a review guide, a study guide,
sample exam or quiz questions. Then:

  1. Read     each file is read page by page (or slide by slide) and redacted, like a student's notes.
  2. Propose  Gemini proposes the smallest set of changes: add, remove or edit a concept, change which weeks use it, and
              copy multiple-choice questions out of the files.
  3. Check    code keeps only changes that point at real concepts and timeline items, checks every quote against the
              file it cites, writes study material for new concepts, checks what the listed prerequisites taught, and
              solves every question blind (disputed keys become drafts).
  4. Apply    nothing changes for students until the owner picks which changes to keep. Students' answers stay.

The model proposes; code validates; a person decides.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from datetime import datetime, timezone

from .ctx import Ctx
from .graph import acyclic_edges
from .llm import EvidencePassage, ItemCard, MapConceptCard, RevisionContext
from .materials import read_material, to_chunks
from .models import BankQuestion, Change, Concept, Edge, Requirement, Revision, RevisionFile, StageTrace
from .retrieval import quote_supported
from .textutil import normalize_name

log = logging.getLogger(__name__)

MAX_FILES = 5
MAX_CHANGES = 40
MAX_QUESTIONS = 12
PASSAGE_CHARS = 120_000  # of all files together, sent to the model


def read_file(engine, label: str, filename: str, data: bytes, mime: str) -> RevisionFile:
    kind, sections = read_material(engine, data, filename, mime)
    return RevisionFile(label=label, filename=(filename or "file")[:120], kind=kind, chunks=to_chunks(sections))


def _passages(files: list[RevisionFile]) -> tuple[list[EvidencePassage], dict[str, tuple[RevisionFile, int]]]:
    out, where, total = [], {}, 0
    for f in files:
        for i, ch in enumerate(f.chunks, start=1):
            label = f"{f.label}.{i}"
            out.append(EvidencePassage(label, f"{f.filename}, {ch.loc}", ch.text))
            where[label] = (f, i - 1)
            total += len(ch.text)
            if total >= PASSAGE_CHARS:
                return out, where
    return out, where


def _appears(snippet: str, text: str) -> bool:
    """Most of the snippet's words are in the text; for math-only snippets ("P(A|B)") with no words, its characters are."""
    if quote_supported(snippet, text):
        return True
    squash = lambda t: re.sub(r"\W+", "", t.lower())  # noqa: E731
    return len(squash(snippet)) >= 6 and all(squash(part) in squash(text) for part in snippet.split() if squash(part))


class RevisionRun:
    """Stand-in for a build's Run: progress goes to the revision, so students keep seeing a ready course."""

    def __init__(self, ctx: Ctx, course, revision: Revision):
        from .mapping import CountingEngine

        self.ctx, self.course, self.revision = ctx, course, revision
        self.engine = CountingEngine(ctx.engine)
        self.trace: list[StageTrace] = []

    def progress(self, stage: str, done: int = 0, total: int = 0) -> None:
        self.revision.stage = f"{stage} ({done} of {total})" if total else stage
        self.ctx.course(self.course.id).revisions.put(self.revision)


def propose(ctx: Ctx, course_id: str, revision_id: str) -> None:
    from .mapping import check_coverage, verify, write_packs

    course = ctx.catalog.get(course_id)
    repo = ctx.course(course_id)
    revision = repo.revisions.get(revision_id)
    if course is None or revision is None or revision.status not in ("queued", "running"):
        return
    revision.status = "running"
    run = RevisionRun(ctx, course, revision)
    try:
        run.progress("Reading your request against the map")
        everything = repo.concepts.list()
        concepts = {c.id: c for c in everything if not c.removed}
        removed = {normalize_name(c.name): c for c in everything if c.removed}
        topics = {t.id: t for t in repo.topics.list()}
        reqs = [r for r in repo.requirements.list() if r.concept_id in concepts and r.topic_id in topics]
        edges = [e for e in repo.edges.list() if e.src in concepts and e.dst in concepts]
        passages, where = _passages(revision.files)
        cards = [MapConceptCard(c.id, c.name, c.summary, c.depth, c.coverage,
                                sorted({r.topic_id for r in reqs if r.concept_id == c.id}),
                                [e.src for e in edges if e.dst == c.id]) for c in concepts.values()]
        items = [ItemCard(t.id, t.week, t.date.isoformat() if t.date else None, t.title, t.details, t.kind)
                 for t in sorted(topics.values(), key=lambda t: (t.week, t.date or datetime.max.date()))]
        plan = run.engine.revise_map(RevisionContext(f"{course.code} {course.title}".strip(), revision.prompt, items, cards, passages))
        revision.summary = plan.summary.strip()[:600]
        revision.not_done = [n.strip()[:300] for n in plan.not_done if n.strip()][:8]

        def cite(source: str | None, quote: str) -> tuple[str, str, bool]:
            hit = where.get((source or "").strip())
            if hit is None:
                return "", quote.strip()[:300], False
            f, i = hit
            return f"{f.filename}, {f.chunks[i].loc}", quote.strip()[:300], bool(quote.strip()) and quote_supported(quote, f.chunks[i].text)

        changes: list[Change] = []
        new: dict[str, Concept] = {}  # normalized name -> concept being added (or restored)
        have = {normalize_name(c.name): c for c in concepts.values()}
        pairs = {(r.concept_id, r.topic_id) for r in reqs}

        by_week: dict[int, str] = {}
        for t in sorted(topics.values(), key=lambda t: (t.kind != "lecture", t.date or datetime.max.date())):
            by_week.setdefault(t.week, t.id)

        def item(ref: str) -> str | None:
            """An item id as given, or "Week 7" / "7" (models sometimes answer with the week instead of the id)."""
            ref = ref.strip()
            if ref in topics:
                return ref
            m = re.fullmatch(r"(?:week|wk)?\s*(\d{1,2})", ref, re.IGNORECASE)
            return by_week.get(int(m.group(1))) if m else None

        def needs_of(refs, cid: str) -> list[Requirement]:
            out, seen = [], set()
            for n in refs:
                tid = item(n.item_id)
                if tid is not None and tid not in seen:
                    seen.add(tid)
                    out.append(Requirement(topic_id=tid, concept_id=cid, importance=n.importance, how_used=n.how_used.strip()[:300]))
            return out

        def checked(ch: Change, source, quote) -> Change:
            ch.source, ch.quote, ch.quote_ok = cite(source, quote)
            if source and not ch.quote_ok:
                ch.selected = False
                ch.note = "The quote it gave isn't in that file. Check it before applying."
            return ch

        for m in plan.changes[:MAX_CHANGES]:
            reason = m.reason.strip()[:300]
            if m.action == "add":
                key = normalize_name(m.name)
                if not key or key in new:
                    continue
                if key in have:  # already on the map: what's left to do is attach it to the right weeks
                    c = have[key]
                    for r in needs_of(m.add_needs, c.id):
                        if (c.id, r.topic_id) not in pairs:
                            changes.append(checked(Change(kind="add_need", concept_id=c.id, name=c.name, topic_id=r.topic_id,
                                                          importance=r.importance, how_used=r.how_used, reason=reason), m.source, m.quote))
                    continue
                if key in removed:  # removed earlier: bring it back as it was
                    c = removed[key].model_copy(update={"removed": False})
                else:
                    c = Concept(name=m.name.strip()[:120], summary=m.summary.strip()[:400], depth=m.depth.strip()[:200], confidence=1.0)
                needs = needs_of(m.add_needs, c.id)
                if not needs:
                    named = ", ".join(n.item_id for n in m.add_needs) or "none"
                    revision.not_done.append(f"{c.name}: proposed, but the weeks it named ({named[:120]}) aren't on the timeline, "
                                             "so it wasn't added. Ask again naming the week.")
                    continue
                new[key] = c
                changes.append(checked(Change(kind="add_concept", concept_id=c.id, name=c.name, summary=c.summary, depth=c.depth,
                                              reason=reason, concept=c, needs=needs,
                                              builds_on=[b for b in dict.fromkeys(m.builds_on) if b in concepts]), m.source, m.quote))
            elif m.concept_id in concepts:
                c = concepts[m.concept_id]
                if m.action == "remove":
                    changes.append(checked(Change(kind="remove_concept", concept_id=c.id, name=c.name, reason=reason), m.source, m.quote))
                elif m.action == "edit":
                    name, summary, depth = m.name.strip()[:120], m.summary.strip()[:400], m.depth.strip()[:200]
                    if (name and name != c.name) or (summary and summary != c.summary) or (depth and depth != c.depth):
                        changes.append(checked(Change(kind="edit_concept", concept_id=c.id, name=name or c.name,
                                                      summary=summary if summary != c.summary else "", depth=depth if depth != c.depth else "",
                                                      reason=reason), m.source, m.quote))
                elif m.action == "needs":
                    lost = [ref for ref in [*(n.item_id for n in m.add_needs), *m.remove_needs] if item(ref) is None]
                    if lost:
                        revision.not_done.append(f"{c.name}: the weeks {', '.join(lost)[:120]} aren't on the timeline, so they were skipped.")
                    for r in needs_of(m.add_needs, c.id):
                        if (c.id, r.topic_id) not in pairs:
                            changes.append(checked(Change(kind="add_need", concept_id=c.id, name=c.name, topic_id=r.topic_id,
                                                          importance=r.importance, how_used=r.how_used, reason=reason), m.source, m.quote))
                    for tid in dict.fromkeys(filter(None, map(item, m.remove_needs))):
                        if (c.id, tid) in pairs:
                            changes.append(checked(Change(kind="remove_need", concept_id=c.id, name=c.name, topic_id=tid, reason=reason),
                                                   m.source, m.quote))
            elif m.concept_id:
                revision.not_done.append(f"A change for an unknown concept ({m.concept_id}) was dropped.")

        # Questions copied from the files: they must be in the file, with 4 distinct options and a valid key.
        sourced: list[BankQuestion] = []
        for q in plan.questions[:MAX_QUESTIONS]:
            target = concepts.get(q.concept) or have.get(normalize_name(q.concept)) or new.get(normalize_name(q.concept))
            choices = [c.strip() for c in q.choices]
            lettered = re.compile(r"^\(?[A-Da-d][.)]\s+")
            if all(lettered.match(c) for c in choices):  # "B) Bayes' rule": the app adds its own letters
                choices = [lettered.sub("", c) for c in choices]
            if target is None or len(choices) != 4 or len(set(choices)) != 4 or not 0 <= q.correct_index < 4 or not q.prompt.strip():
                continue
            prompt = re.sub(r"^\s*(?:Q(?:uestion)?\s*)?\d{1,2}[.):]\s+", "", q.prompt).strip()  # the file's own numbering
            bq = BankQuestion(concept_id=target.id, prompt=prompt, choices=choices, correct_index=q.correct_index,
                              explanation=q.explanation.strip(), origin="instructor", order=-1)
            ch = Change(kind="add_question", concept_id=target.id, name=target.name, questions=[bq],
                        reason="Answer key from the file." if q.key_from_file else "The file has no answer key; the key was worked out.")
            ch.source, _, _ = cite(q.source, q.prompt)
            hit = where.get((q.source or "").strip())
            # the question and its options must be in the passage it cites (a short prompt alone proves little)
            ch.quote_ok = hit is not None and _appears(f"{prompt} {' '.join(choices)}", hit[0].chunks[hit[1]].text)
            if not ch.quote_ok:
                ch.selected, ch.note = False, "This question wasn't found in your files. Check it before applying."
            changes.append(ch)
            sourced.append(bq)

        # New concepts get the same treatment as a build: study material, what the prerequisites taught, verified keys.
        fresh = [ch.concept for ch in changes if ch.kind == "add_concept" and ch.concept and not ch.concept.refresher]
        packs: list[BankQuestion] = []
        if fresh:
            with_needs = [r for ch in changes if ch.kind == "add_concept" for r in ch.needs]
            links = [Edge(src=b, dst=ch.concept_id) for ch in changes if ch.kind == "add_concept" for b in ch.builds_on]
            with run_stage(run, "Writing study material for new concepts"):
                packs = write_packs(run, fresh, with_needs, links)  # type: ignore[arg-type]
            with run_stage(run, "Checking what prerequisites taught"):
                check_coverage(run, fresh)  # type: ignore[arg-type]
        with run_stage(run, "Double-checking answer keys"):
            verify(run, sourced + packs)  # type: ignore[arg-type]
        for ch in changes:
            if ch.kind == "add_concept" and ch.concept:
                ch.questions = [q for q in packs if q.concept_id == ch.concept_id]
            if ch.kind == "add_question" and ch.questions and ch.questions[0].verification == "disagreed":
                ch.note = (ch.note + " " if ch.note else "") + (
                    "An independent solve disagrees with this answer key, so it stays a draft until you approve it in the list below.")
        revision.changes = changes
        revision.status, revision.stage = "ready", ""
        if not changes and not revision.not_done:
            revision.not_done = ["Nothing in the request or the files called for a change to the map."]
    except Exception as exc:
        log.exception("revision %s failed", revision_id)
        from .llm.failures import describe_failure

        revision.status = "error"
        _, revision.error = describe_failure(exc, RuntimeError)
    revision.calls = dict(run.engine.calls)
    repo.revisions.put(revision)


@contextmanager
def run_stage(run: RevisionRun, name: str):
    run.progress(name)
    yield


def apply(ctx: Ctx, course_id: str, revision: Revision, chosen: list[str]) -> dict:
    """Apply the chosen changes. Students' answers stay; a change whose concept or week no longer exists is skipped."""
    course = ctx.catalog.get(course_id)
    repo = ctx.course(course_id)
    picked = [ch for ch in revision.changes if ch.id in set(chosen)]
    applied, skipped = [], []
    with ctx.lock(course_id):
        concepts = {c.id: c for c in repo.concepts.list()}
        topics = {t.id for t in repo.topics.list()}
        reqs = repo.requirements.list()
        edges = repo.edges.list()
        order = {"add_concept": 0, "edit_concept": 1, "add_need": 2, "remove_need": 3, "add_question": 4, "remove_concept": 5}
        for ch in sorted(picked, key=lambda c: order[c.kind]):
            c = concepts.get(ch.concept_id or "")
            if ch.kind == "add_concept" and ch.concept:
                concept = ch.concept.model_copy(update={"removed": False})
                repo.concepts.put(concept)
                concepts[concept.id] = concept
                have = {(r.concept_id, r.topic_id) for r in reqs}
                new_reqs = [r for r in ch.needs if r.topic_id in topics and (r.concept_id, r.topic_id) not in have]
                repo.requirements.put_many(new_reqs)
                reqs += new_reqs
                repo.questions.put_many(ch.questions)
                live = [c for c in concepts.values() if not c.removed]
                index = {c.id: i for i, c in enumerate(live)}
                candidates = [(index[e.src], index[e.dst], e.confidence) for e in edges if e.src in index and e.dst in index]
                wanted = [(index[b], index[concept.id], 1.0) for b in ch.builds_on if b in index]
                kept, _ = acyclic_edges(candidates + wanted)
                new_edges = [Edge(src=live[s].id, dst=live[d].id) for s, d, w in kept if (s, d, w) in wanted]
                repo.edges.put_many(new_edges)
                edges += new_edges
            elif c is None:
                skipped.append(f"{ch.name}: no longer on the map")
                continue
            elif ch.kind == "edit_concept":
                c.name = ch.name or c.name
                c.summary = ch.summary or c.summary
                c.depth = ch.depth or c.depth
                repo.concepts.put(c)
            elif ch.kind == "remove_concept":
                c.removed = True
                repo.concepts.put(c)
            elif ch.kind == "add_need":
                if ch.topic_id not in topics:
                    skipped.append(f"{ch.name}: that week is no longer on the timeline")
                    continue
                if not any(r.concept_id == c.id and r.topic_id == ch.topic_id for r in reqs):
                    r = Requirement(topic_id=ch.topic_id, concept_id=c.id, importance=ch.importance, how_used=ch.how_used)
                    repo.requirements.put(r)
                    reqs.append(r)
            elif ch.kind == "remove_need":
                gone = [r.id for r in reqs if r.concept_id == c.id and r.topic_id == ch.topic_id]
                repo.requirements.delete_many(gone)
                reqs = [r for r in reqs if r.id not in gone]
            elif ch.kind == "add_question":
                repo.questions.put_many(ch.questions)
            applied.append(ch.id)
        revision.applied = applied
        revision.status, revision.applied_at = "applied", datetime.now(timezone.utc)
        repo.revisions.put(revision)
        counts: dict[str, int] = {}
        for ch in picked:
            if ch.id in applied:
                counts[ch.kind] = counts.get(ch.kind, 0) + 1
        words = {"add_concept": "added", "remove_concept": "removed", "edit_concept": "edited", "add_need": "weeks added",
                 "remove_need": "weeks removed", "add_question": "questions from your files"}
        if course is not None:
            course.build.trace.append(StageTrace(stage="Revised by the course owner", notes=[
                f"request: {revision.prompt[:160]}", *(f"{words[k]}: {n}" for k, n in counts.items()),
                *([f"files: {', '.join(f.filename for f in revision.files)}"] if revision.files else []),
                *(f"skipped: {s}" for s in skipped)]))
            ctx.catalog.put(course)
    return {"applied": len(applied), "skipped": skipped,
            "added_concepts": any(ch.kind == "add_concept" and ch.id in applied for ch in picked)}


def view(revision: Revision, names: dict[str, str], weeks: dict[str, tuple[int, str]]) -> dict:
    """What the owner sees. File text stays on the server; answer keys are shown (the owner reviews them)."""

    def need(tid: str | None) -> dict | None:
        if tid is None:
            return None
        week, title = weeks.get(tid, (0, "a week no longer on the timeline"))
        return {"topic_id": tid, "week": week, "title": title}

    return {
        "id": revision.id, "prompt": revision.prompt, "status": revision.status, "stage": revision.stage, "error": revision.error,
        "summary": revision.summary, "not_done": revision.not_done, "created_at": revision.created_at.isoformat(),
        "applied_at": revision.applied_at.isoformat() if revision.applied_at else None, "applied": revision.applied,
        "files": [{"filename": f.filename, "kind": f.kind, "parts": len({c.loc for c in f.chunks})} for f in revision.files],
        "calls": sum(revision.calls.values()),
        "changes": [{
            "id": ch.id, "kind": ch.kind, "concept_id": ch.concept_id, "name": ch.name,
            "current_name": names.get(ch.concept_id or "", ""), "summary": ch.summary, "depth": ch.depth,
            "need": need(ch.topic_id), "importance": ch.importance, "how_used": ch.how_used,
            "reason": ch.reason, "source": ch.source, "quote": ch.quote, "quote_ok": ch.quote_ok, "selected": ch.selected, "note": ch.note,
            "needs": [need(r.topic_id) for r in ch.needs],
            "builds_on": [names.get(b, b) for b in ch.builds_on],
            "coverage": ch.concept.coverage if ch.concept else None, "covered_by": ch.concept.covered_by if ch.concept else None,
            "questions": [{"prompt": q.prompt, "choices": q.choices, "correct_index": q.correct_index, "explanation": q.explanation,
                           "verification": q.verification, "status": q.status} for q in ch.questions],
        } for ch in revision.changes],
    }

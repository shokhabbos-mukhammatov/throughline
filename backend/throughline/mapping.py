"""Building a course map from a syllabus.

Pipeline (each stage is timed and its model calls counted in course.build.trace):
  1. Read      syllabus -> timeline, prerequisite statement, AI policy, topics taught here.
  2. Bulletin  the course and its listed prerequisites from the SF State Bulletin.
  3. Map       for each batch of timeline items, N independent runs propose the prior knowledge it relies on
               and what each concept builds on.
  4. Resolve   entity resolution clusters the proposed names; a concept or relation is kept only when a
               majority of runs agree (agreement = confidence); relations become a cycle-free graph.
  5. Evidence  hybrid retrieval over the Bulletin and prerequisite syllabi; the model judges coverage from
               the retrieved passages only; code checks every quote. Coverage: listed / likely / missing / unknown.
  6. Study     refresher, learn path, resources from a fixed catalog, three questions per concept.
  7. Verify    every answer key is solved blind by an independent call; disagreements are hidden until approved.

The model proposes; code validates and decides.
"""

from __future__ import annotations

import logging
import math
import random
import re
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import bulletin
from .ctx import Ctx
from .graph import acyclic_edges, resolve, transitive_reduction
from .llm import ConceptCard, CourseContext, CoverageRequest, Engine, ItemCard, QuestionCard, ResourceCard
from .llm.failures import describe_failure
from .llm.schemas import SyllabusParse
from .models import AiPolicy, BankQuestion, Concept, Course, Edge, Evidence, Requirement, Resource, StageTrace, Topic
from .retrieval import EvidenceIndex, build_corpus, quote_supported
from .seed import library
from .textutil import contains_phrase, course_code, normalize_name

log = logging.getLogger(__name__)

ITEMS_PER_CALL = 6
CONCEPTS_PER_CALL = 3
COVERAGE_PER_CALL = 6
QUESTIONS_PER_SOLVE = 12
PARALLEL = 4
JOBS = ("read_document", "parse_syllabus", "map_prerequisites", "embed", "judge_same", "judge_coverage", "write_packs", "solve")
NEGATION = ("do not need", "don't need", "not required", "no prior", "not needed", "not assume", "without any")


class BuildFailed(RuntimeError):
    pass


def _iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
class CountingEngine:
    """Wraps an engine and counts model calls per job, so each stage's cost is visible."""

    def __init__(self, engine: Engine):
        self._engine = engine
        self.calls: Counter = Counter()
        self._lock = threading.Lock()

    @property
    def online(self) -> bool:
        return self._engine.online

    @property
    def label(self) -> str:
        return self._engine.label

    def __getattr__(self, name):
        attr = getattr(self._engine, name)
        if name not in JOBS or not callable(attr):
            return attr

        def counted(*args, **kwargs):
            with self._lock:
                self.calls[name] += 1
            return attr(*args, **kwargs)

        return counted


@dataclass
class Run:
    ctx: Ctx
    course: Course
    engine: CountingEngine
    trace: list[StageTrace] = field(default_factory=list)

    def progress(self, stage: str, done: int = 0, total: int = 0) -> None:
        b = self.course.build
        b.status, b.stage, b.done, b.total = "running", stage, done, total
        b.trace = self.trace
        self.ctx.catalog.put(self.course)

    @contextmanager
    def stage(self, name: str):
        before = Counter(self.engine.calls)
        entry = StageTrace(stage=name)
        self.trace.append(entry)
        self.progress(name)
        t0 = time.perf_counter()
        try:
            yield entry
        finally:
            entry.ms = int((time.perf_counter() - t0) * 1000)
            entry.calls = {k: v - before.get(k, 0) for k, v in self.engine.calls.items() if v - before.get(k, 0)}


# Stage 1: timeline
def apply_parse(course: Course, parsed: SyllabusParse) -> list[Topic]:
    if not course.code or course.code.upper() in {"COURSE", "NEW COURSE"}:
        course.code = course_code(parsed.code)
    course.title = course.title or parsed.title
    course.term = parsed.term or course.term
    course.official_prereqs = [course_code(c) for c in parsed.official_prereqs]
    course.prereq_text = parsed.prereq_text
    course.prereq_routes = parsed.prereq_routes
    course.informal_requirements = parsed.informal_requirements
    course.instructor_notes = parsed.instructor_notes
    course.ai_policy = AiPolicy(stance=parsed.ai_stance, summary=parsed.ai_summary)
    course.timeline_kind = parsed.timeline_kind
    course.resources = [Resource(title=r.title, url=r.url, detail=r.detail, kind="syllabus") for r in parsed.free_resources if r.title]

    start = _iso(parsed.term_start)
    dated = [(it, _iso(it.date)) for it in parsed.timeline]
    if start is None:
        # Back out the first week from any dated lecture week.
        anchors = [(it.week, d) for it, d in dated if d and it.week >= 1 and it.kind == "lecture"]
        if anchors:
            wk, d = min(anchors)
            start = d - timedelta(weeks=wk - 1)
        else:
            # Only dated assessments: count weeks from the earliest one (shown to students as an estimate).
            start = min((d for _, d in dated if d), default=None)
    if start is not None:
        start = start - timedelta(days=start.weekday())  # Monday of week 1
    course.term_start = start
    course.term_end = _iso(parsed.term_end)

    topics = []
    for it, d in dated:
        week = it.week
        if d is not None and start is not None and (week < 1 or it.kind == "assessment"):
            week = (d - start).days // 7 + 1
        if d is None and start is not None and week >= 1:
            d = start + timedelta(weeks=week - 1)
        if week < 1 or not it.title.strip():
            continue
        topics.append(Topic(week=week, date=d, title=it.title.strip()[:200], details=it.details.strip()[:600],
                            kind=it.kind, estimated=it.estimated or (it.date is None and d is not None)))
    topics.sort(key=lambda t: (t.week, t.date or date.max, t.kind))
    return topics


# Stages 3-4: map with self-consistency, resolve, build the graph
@dataclass
class Proposal:
    sample: int
    item_id: str
    name: str
    summary: str
    importance: str
    how_used: str
    depth: str
    covered_by: str | None
    evidence: str
    builds_on: list[tuple[str, str]]


def _bulletin_lines(course: Course) -> list[str]:
    own = course_code(course.code)
    return [f"{b.code} {b.title}: {b.description} Prerequisites: {b.prerequisites or 'none listed'}"
            for b in course.bulletin if course_code(b.code) != own]


def propose(run: Run, topics: list[Topic], taught_here: list[str]) -> list[Proposal]:
    course, settings = run.course, run.ctx.settings
    cctx = CourseContext(
        label=f"{course.code} {course.title}".strip(), prereq_text=course.prereq_text, official_prereqs=course.official_prereqs,
        informal_requirements=course.informal_requirements, instructor_notes=course.instructor_notes,
        taught_here=taught_here, bulletin=_bulletin_lines(course),
    )
    samples = max(1, settings.mapping_samples if run.engine.online else 1)  # the offline engine is deterministic
    batches = [topics[i : i + ITEMS_PER_CALL] for i in range(0, len(topics), ITEMS_PER_CALL)]
    proposals: list[Proposal] = []
    known: list[str] = []
    for n, batch in enumerate(batches):
        run.progress("Mapping prerequisites", n, len(batches))
        valid = {t.id for t in batch}

        def one(sample: int, batch=batch):
            # Each run sees the items in a different order and from a different angle.
            order = batch if sample % 2 == 0 else list(reversed(batch))
            cards = [ItemCard(t.id, t.week, t.date.isoformat() if t.date else None, t.title, t.details, t.kind) for t in order]
            try:
                return sample, run.engine.map_prerequisites(cctx, cards, known, sample=sample)
            except Exception as exc:
                log.warning("map_prerequisites failed (weeks %s, run %d): %s", [t.week for t in batch], sample, exc)
                return sample, None

        with ThreadPoolExecutor(max_workers=min(samples, PARALLEL)) as pool:
            for sample, result in pool.map(one, range(samples)):
                if result is None:
                    continue
                for item in result.items:
                    if item.item_id not in valid:  # drop ids the model invented
                        continue
                    for r in item.requires[:4]:
                        if not normalize_name(r.name):
                            continue
                        proposals.append(Proposal(
                            sample, item.item_id, r.name.strip()[:120], r.summary.strip()[:400], r.importance,
                            r.how_used.strip()[:300], r.depth.strip()[:200],
                            course_code(r.covered_by) if r.covered_by else None, r.evidence.strip()[:400],
                            [(f.name.strip()[:120], f.summary.strip()[:300]) for f in r.builds_on[:2] if normalize_name(f.name)],
                        ))
        for p in proposals:
            if p.name not in known:
                known.append(p.name)
    return proposals


def assemble(run: Run, proposals: list[Proposal], topics: list[Topic]) -> tuple[list[Concept], list[Requirement], list[Edge], dict]:
    """Resolve names, vote across runs, and build concepts, requirements and a cycle-free graph."""
    course = run.course
    samples = len({p.sample for p in proposals}) or 1
    majority = math.ceil(samples / 2)
    listed = {course_code(c) for c in course.official_prereqs} | {course_code(b.code) for b in course.bulletin}

    names = [(p.name, p.summary) for p in proposals] + [f for p in proposals for f in p.builds_on]
    res = resolve(run.engine, names)

    # Votes: which runs proposed concept-cluster c for item i.
    votes: dict[tuple[str, int], set[int]] = {}
    details: dict[tuple[str, int], list[Proposal]] = {}
    for p in proposals:
        key = (p.item_id, res.cluster_of(p.name).id)
        votes.setdefault(key, set()).add(p.sample)
        details.setdefault(key, []).append(p)
    kept = {k for k, v in votes.items() if len(v) >= majority}

    # Concept-level confidence: share of runs that proposed it anywhere.
    runs_per_cluster: dict[int, set[int]] = {}
    for (item, cid), v in votes.items():
        runs_per_cluster.setdefault(cid, set()).update(v)

    concepts: dict[int, Concept] = {}

    def concept_for(cid: int, foundation: bool) -> Concept:
        if cid not in concepts:
            cl = res.clusters[cid]
            concepts[cid] = Concept(name=cl.name, aliases=cl.aliases[:6], summary=cl.summary[:400], foundation=foundation,
                                    confidence=round(len(runs_per_cluster.get(cid, set())) / samples, 2) if not foundation else 0.0)
        return concepts[cid]

    reqs: list[Requirement] = []
    for item_id, cid in sorted(kept, key=lambda k: (k[0], k[1])):
        group = details[(item_id, cid)]
        c = concept_for(cid, foundation=False)
        c.foundation = False
        importance = Counter(p.importance for p in group).most_common(1)[0][0]
        best = group[0]
        reqs.append(Requirement(topic_id=item_id, concept_id=c.id, importance=importance, how_used=best.how_used))
        if not c.depth:
            c.depth = best.depth
        cover = Counter(p.covered_by for p in group if p.covered_by and p.covered_by in listed).most_common(1)
        if cover and not c.covered_by:
            c.covered_by = cover[0][0]
            c.evidence = next((p.evidence for p in group if p.covered_by == c.covered_by and p.evidence), "")
        if not c.evidence:
            c.evidence = next((p.evidence for p in group if p.evidence), "")

    # Relations: "dependent builds on foundation", kept when a majority of runs proposed them.
    edge_votes: dict[tuple[int, int], set[int]] = {}
    foundation_summary: dict[int, str] = {}
    for p in proposals:
        dep = res.cluster_of(p.name).id
        for fname, fsum in p.builds_on:
            src = res.cluster_of(fname).id
            if src != dep:
                edge_votes.setdefault((src, dep), set()).add(p.sample)
                foundation_summary.setdefault(src, fsum)
    required = {res.cluster_of(c.name).id for c in concepts.values()}
    candidates = [(s, d, len(v) / samples) for (s, d), v in edge_votes.items() if len(v) >= majority and d in required]
    dag, dropped = acyclic_edges(candidates)
    dag = transitive_reduction(dag)
    for src, _, weight in dag:
        f = concept_for(src, foundation=src not in required)
        if f.foundation:
            f.confidence = max(f.confidence, round(weight, 2))
            f.summary = f.summary or foundation_summary.get(src, "")[:400]
    edges = [Edge(src=concepts[s].id, dst=concepts[d].id, confidence=round(w, 2)) for s, d, w in dag if s in concepts and d in concepts]

    stats = {
        **{f"resolve_{k}": v for k, v in res.stats.items()},
        "runs": samples,
        "proposed_pairs": len(votes),
        "kept_pairs": len(kept),
        "edges_kept": len(edges),
        "edges_dropped_for_cycles": dropped,
        "foundations": sum(1 for c in concepts.values() if c.foundation),
    }
    return list(concepts.values()), reqs, edges, stats


# Stage 5: evidence
def _instructor_negation(course: Course, c: Concept) -> str | None:
    """A syllabus line saying students don't need this concept (strong evidence no prerequisite covers it)."""
    lib = library.find(c.name)
    phrases = [c.name, *c.aliases, *(lib.keywords if lib else ())]
    for note in [*course.instructor_notes, *course.informal_requirements]:
        low = note.lower()
        negated = any(n in low for n in NEGATION) or re.search(r"\bno\b[^.]*\b(required|needed|necessary|assumed|expected)\b", low)
        if negated and any(contains_phrase(note, ph) for ph in phrases):
            return note
    return None


def check_coverage(run: Run, concepts: list[Concept]) -> dict:
    course = run.course
    listed = {course_code(c) for c in course.official_prereqs}
    corpus = build_corpus(run.ctx.store, course)
    index = EvidenceIndex(run.engine, corpus)
    have_syllabus = {p.code for p in corpus if p.kind == "prereq_syllabus"}
    queries = [f"{c.name}. {' '.join(c.aliases[:3])}. {c.summary}" for c in concepts]
    try:
        qvecs = run.engine.embed(queries) if corpus and concepts else [None] * len(concepts)
    except Exception:
        qvecs = [None] * len(concepts)

    requests, retrieved = [], {}
    for c, query, qv in zip(concepts, queries, qvecs):
        hits = [p for p in index.search(query, qv, k=4) if p.kind != "this_syllabus"]
        retrieved[c.id] = {p.label: p for p in hits}
        if hits:
            requests.append(CoverageRequest(c.id, c.name, c.summary, c.depth, [p.card() for p in hits]))

    judgments = {}
    batches = [requests[i : i + COVERAGE_PER_CALL] for i in range(0, len(requests), COVERAGE_PER_CALL)]

    def run_batch(batch):
        try:
            return run.engine.judge_coverage(batch).judgments
        except Exception as exc:
            log.warning("judge_coverage failed: %s", exc)
            return []

    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for result in pool.map(run_batch, batches):
            for j in result:
                judgments[j.concept_id] = j

    counts = Counter()
    rejected_quotes = 0
    for c in concepts:
        c.evidence_items = []
        negation = _instructor_negation(course, c)
        j = judgments.get(c.id)
        cited = retrieved.get(c.id, {}).get(j.passage) if j and j.passage else None
        if j and cited and j.verdict != "unrelated" and not quote_supported(j.quote, cited.text):
            rejected_quotes += 1  # the model's quote isn't in the passage it cited: don't trust the verdict
            cited = None
        if cited and cited.code and cited.code not in listed:
            cited = None  # evidence about a course that isn't a listed prerequisite doesn't count
        if negation:
            c.coverage, c.covered_by = "missing", None
            c.evidence = f"The syllabus says: “{negation}”"
            c.evidence_items.append(Evidence(source="This syllabus", quote=negation, verdict="unrelated"))
        elif cited and j and j.verdict == "teaches":
            c.coverage, c.covered_by = "listed", cited.code
            c.evidence = f"{cited.source}: “{j.quote}”"
            c.evidence_items.append(Evidence(source=cited.source, quote=j.quote, verdict="teaches"))
        elif cited and j and j.verdict == "partial":
            c.coverage, c.covered_by = "likely", cited.code
            c.evidence = f"Partly covered. {cited.source}: “{j.quote}”"
            c.evidence_items.append(Evidence(source=cited.source, quote=j.quote, verdict="partial"))
        elif listed and listed & have_syllabus and (j is None or j.verdict == "unrelated"):
            c.coverage, c.covered_by = "missing", None
            checked = ", ".join(sorted(listed & have_syllabus))
            c.evidence = f"Not found in the {checked} syllabus."
        elif c.covered_by and c.covered_by in listed:
            c.coverage = "likely"
            c.evidence = f"Usually taught in {c.covered_by}; its Bulletin description doesn't confirm it." + (f" {c.evidence}" if c.evidence else "")
        elif not listed:
            c.coverage, c.covered_by = "missing", None
            c.evidence = "The syllabus lists no prerequisite course that would teach it."
        else:
            c.coverage, c.covered_by = "unknown", None
            c.evidence = ("The Bulletin descriptions of " + ", ".join(sorted(listed)) + " don't mention it. "
                          "Add the prerequisite's syllabus to check.")
        c.hidden = c.coverage == "missing"
        counts[c.coverage] += 1
    return {"passages": len(corpus), "prereq_syllabi": sorted(have_syllabus), "judged": len(judgments),
            "rejected_quotes": rejected_quotes, **{f"coverage_{k}": v for k, v in counts.items()}}


def coverage_notes(stats: dict) -> list[str]:
    """The coverage stage's numbers as short sentences for the build trace."""
    syllabi = ", ".join(stats["prereq_syllabi"]) or "none (Bulletin only)"
    return [
        f"{stats['passages']} passages indexed",
        f"prerequisite syllabi: {syllabi}",
        f"{stats['judged']} coverage judgments",
        f"{stats['rejected_quotes']} quotes rejected as not in the cited passage",
        " · ".join(f"{k}: {stats.get('coverage_' + k, 0)}" for k in ("listed", "likely", "missing", "unknown")),
    ]


# Stage 6: study packs
def resource_catalog(course: Course) -> tuple[list[ResourceCard], dict[str, Resource]]:
    cards, lookup = [], {}
    for i, r in enumerate(course.resources):
        rid = f"syl{i + 1}"
        cards.append(ResourceCard(rid, f"{r.title} (recommended in the syllabus)", r.detail))
        lookup[rid] = r
    for r in library.RESOURCES:
        cards.append(ResourceCard(r.id, r.title, r.detail, list(r.subjects)))
        lookup[r.id] = Resource(title=r.title, url=r.url, detail=r.detail, kind="open_textbook")
    return cards, lookup


def _shuffled(q, seed: str) -> tuple[list[str], int] | None:
    choices = [c.strip() for c in q.choices]
    if len(choices) != 4 or len(set(choices)) != 4 or not (0 <= q.correct_index < 4):
        return None
    correct = choices[q.correct_index]
    random.Random(seed).shuffle(choices)  # undo any position bias in generated keys
    return choices, choices.index(correct)


def write_packs(run: Run, concepts: list[Concept], reqs: list[Requirement], edges: list[Edge]) -> list[BankQuestion]:
    course = run.course
    cards, lookup = resource_catalog(course)
    uses: dict[str, list[str]] = {}
    for r in reqs:
        uses.setdefault(r.concept_id, []).append(r.how_used)
    names = {c.id: c.name for c in concepts}
    for e in edges:
        uses.setdefault(e.src, []).append(f"Foundation for {names.get(e.dst, 'a later concept')}.")
    by_id = {c.id: c for c in concepts}
    batches = [concepts[i : i + CONCEPTS_PER_CALL] for i in range(0, len(concepts), CONCEPTS_PER_CALL)]
    label = f"{course.code} {course.title}".strip()
    questions: list[BankQuestion] = []

    def one(batch: list[Concept]):
        ccards = [ConceptCard(c.id, c.name, c.summary, c.depth, uses.get(c.id, []), c.hidden) for c in batch]
        try:
            return run.engine.write_packs(label, ccards, cards).packs
        except Exception as exc:
            log.warning("write_packs failed for %s: %s", [c.name for c in batch], exc)
            return []

    done = 0
    run.progress("Writing study material", 0, len(concepts))
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for packs in pool.map(one, batches):
            for pack in packs:
                c = by_id.get(pack.concept_id)
                if c is None:
                    continue
                c.refresher, c.learn_outline = pack.refresher.strip(), pack.learn_outline.strip()
                c.refresh_minutes, c.learn_minutes = pack.refresh_minutes, pack.learn_minutes
                c.resources = [lookup[r] for r in dict.fromkeys(pack.resource_ids) if r in lookup][:3]
                for order, q in enumerate(pack.questions[:3]):
                    bq = BankQuestion(concept_id=c.id, prompt=q.prompt.strip(), choices=[], correct_index=0,
                                      explanation=q.explanation.strip(), order=order, origin="ai" if run.engine.online else "sample")
                    placed = _shuffled(q, bq.id) if run.engine.online else (list(q.choices), q.correct_index)
                    if placed is None:
                        continue
                    bq.choices, bq.correct_index = placed
                    questions.append(bq)
            done += len(packs)
            run.progress("Writing study material", min(done, len(concepts)), len(concepts))
    return questions


# Stage 7: verification
def verify(run: Run, questions: list[BankQuestion]) -> dict:
    if not run.engine.online:
        return {"verified": 0, "disputed": 0, "note": "offline: hand-written questions, not re-solved"}
    batches = [questions[i : i + QUESTIONS_PER_SOLVE] for i in range(0, len(questions), QUESTIONS_PER_SOLVE)]
    by_id = {q.id: q for q in questions}

    def one(batch: list[BankQuestion]):
        try:
            return run.engine.solve([QuestionCard(q.id, q.prompt, q.choices) for q in batch]).solutions
        except Exception as exc:
            log.warning("solve failed: %s", exc)
            return []

    checked = disputed = 0
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        for solutions in pool.map(one, batches):
            for s in solutions:
                q = by_id.get(s.question_id)
                if q is None:
                    continue
                checked += 1
                if s.choice == q.correct_index and not s.note.strip():
                    q.verification = "agreed"
                else:
                    disputed += 1
                    q.verification, q.status = "disagreed", "draft"  # hidden from students until a person approves it
                    q.verification_note = s.note.strip()[:300] or f"An independent solve picked option {s.choice + 1}."
            run.progress("Double-checking answer keys", checked, len(questions))
    return {"verified": checked, "disputed": disputed}
def build_course(ctx: Ctx, course_id: str, hint_code: str = "") -> None:
    course = ctx.catalog.get(course_id)
    if course is None:
        return
    run = Run(ctx=ctx, course=course, engine=CountingEngine(ctx.engine))
    repo = ctx.course(course_id)
    try:
        with run.stage("Reading the syllabus") as st:
            parsed = run.engine.parse_syllabus(course.syllabus_text, hint_code or course.code)
            topics = apply_parse(course, parsed)
            st.notes = [f"timeline: {course.timeline_kind}", f"{len(topics)} items"]
            if not topics:
                raise BuildFailed("Couldn't find a schedule, dated assessments or a topic list in this syllabus.")

        with run.stage("Checking the SF State Bulletin") as st:
            course.bulletin = bulletin.chain(course.code, course.official_prereqs, live=ctx.settings.bulletin_live)
            if not course.official_prereqs and course.bulletin:
                course.official_prereqs = course.bulletin[0].prereq_codes
            st.notes = [f"{b.code} ({b.source})" for b in course.bulletin] or ["no entries found"]

        with run.stage("Mapping prerequisites") as st:
            proposals = propose(run, topics, parsed.taught_here)
            st.notes = [f"{len(proposals)} proposals from {len({p.sample for p in proposals}) or 0} independent runs"]

        with run.stage("Resolving concepts and building the graph") as st:
            concepts, reqs, edges, stats = assemble(run, proposals, topics)
            st.notes = [f"{k.replace('_', ' ')}: {v}" for k, v in stats.items()]
            if not concepts:
                raise BuildFailed("No prerequisite knowledge was found for this syllabus.")

        with run.stage("Checking what prerequisites taught") as st:
            st.notes = coverage_notes(check_coverage(run, concepts))

        with run.stage("Writing study material") as st:
            questions = write_packs(run, concepts, reqs, edges)
            st.notes = [f"{len(questions)} questions for {len(concepts)} concepts"]

        with run.stage("Double-checking answer keys") as st:
            stats = verify(run, questions)
            st.notes = [f"{k.replace('_', ' ')}: {v}" for k, v in stats.items()]

        with ctx.lock(course_id):
            repo.clear_map()
            repo.responses.delete_many([r.id for r in repo.responses.list()])
            repo.topics.put_many(topics)
            repo.concepts.put_many(concepts)
            repo.edges.put_many(edges)
            repo.requirements.put_many(reqs)
            repo.questions.put_many(questions)
            for e in repo.enrollments.list():
                e.self_report = {}
                repo.enrollments.put(e)
        course.build.status, course.build.stage, course.build.error, course.build.error_kind = "ready", "Ready", None, ""
        course.build.done = course.build.total = 0
        course.build.trace = run.trace
        ctx.catalog.put(course)
    except Exception as exc:
        log.exception("course build failed")
        course.build.status = "error"
        course.build.error_kind, course.build.error = describe_failure(exc, BuildFailed)
        course.build.trace = run.trace
        ctx.catalog.put(course)


def recheck_coverage(ctx: Ctx, course_id: str) -> None:
    """Re-run only the evidence stage, e.g. after a prerequisite's syllabus was added."""
    course = ctx.catalog.get(course_id)
    if course is None:
        return
    repo = ctx.course(course_id)
    run = Run(ctx=ctx, course=course, engine=CountingEngine(ctx.engine), trace=list(course.build.trace))
    try:
        with ctx.lock(course_id):
            concepts = repo.concepts.list()
            with run.stage("Re-checking what prerequisites taught") as st:
                st.notes = coverage_notes(check_coverage(run, concepts))
            repo.concepts.put_many(concepts)
        course.build.status, course.build.stage, course.build.error = "ready", "Ready", None
    except Exception as exc:
        log.exception("coverage recheck failed")
        kind, message = describe_failure(exc, BuildFailed)
        course.build.status, course.build.error, course.build.error_kind = "ready", f"Coverage re-check failed. {message}", kind
    course.build.trace = run.trace
    ctx.catalog.put(course)

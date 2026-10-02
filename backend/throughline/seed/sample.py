"""A fictional sample course for demos and tests.

DEMO 410 "Applied Machine Learning for Scientists" is invented. It mirrors a pattern seen in real
syllabi: the listed prerequisite is a statistics course, and the instructor says no calculus or linear
algebra is needed, yet later weeks rely on derivatives, vectors and matrices. Today always falls in
week 4 so the next weeks are the interesting ones. Nothing here comes from a real SF State syllabus.

`create_sample` builds the map from the hand-written library (no AI calls), connects concepts with the
library's prerequisite relations, and runs the real evidence stage (offline engine) against a fictional
DEMO 212 syllabus, so coverage labels are computed rather than typed in. It can add a simulated class so
the class view has data. Simulated students are flagged and labeled in the UI.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from ..ctx import Ctx
from ..graph import acyclic_edges, transitive_reduction
from ..llm.offline import OfflineEngine
from ..models import (
    AiPolicy,
    BankQuestion,
    BulletinEntry,
    Concept,
    Course,
    Edge,
    Enrollment,
    PrereqDoc,
    Requirement,
    Resource,
    Response,
    StageTrace,
    Topic,
)
from . import library

CODE, TITLE = "DEMO 410", "Applied Machine Learning for Scientists"
PREREQ = "DEMO 212 (Statistics for Scientists) or equivalent, or permission of the instructor."
BULLETIN = [
    BulletinEntry(code="DEMO 410", title=TITLE, description="Fictional sample course.", prerequisites=PREREQ,
                  prereq_codes=["DEMO 212"], source="Sample (fictional)"),
    BulletinEntry(code="DEMO 212", title="Statistics for Scientists",
                  description="Descriptive statistics, probability, and simple linear regression for science majors.",
                  prerequisites="None.", source="Sample (fictional)"),
]
# The (fictional) prerequisite's own syllabus: the evidence stage checks coverage against it.
DEMO_212_SYLLABUS = """DEMO 212 Statistics for Scientists (sample syllabus, fictional)
Week 1: Describing data: mean, median, standard deviation, histograms and box plots
Week 2: Probability rules, conditional probability and independence
Week 3: Random variables and the normal distribution
Week 4: Sampling distributions and the central limit theorem
Week 5: Confidence intervals for a mean and a proportion
Week 6: Hypothesis tests and p-values
Week 7: Correlation and simple linear regression: fitting a line, interpreting slope and R-squared
Week 8: Review and final exam
Calculations are done with a graphing calculator; no programming is required."""

# week, title, details, [(concept key, importance, how used)]
SCHEDULE: list[tuple[int, str, str, list[tuple[str, str, str]]]] = [
    (1, "Python notebooks and data frames", "Colab setup, pandas basics, first plots",
     [("python", "essential", "Every lab is a Python notebook; you edit loops, functions and lists from day one.")]),
    (2, "Exploring a dataset", "Summaries, distributions, outliers",
     [("desc-stats", "essential", "You summarize each feature with mean, median and standard deviation before modeling."),
      ("python", "essential", "Summaries are computed with pandas in a notebook.")]),
    (3, "Linear regression as a predictive model", "Train/test split, fitting a line, error metrics",
     [("slr", "essential", "We start from the regression line you met in statistics and use it to predict."),
      ("desc-stats", "helpful", "Error metrics are averages of squared or absolute residuals.")]),
    (4, "Multiple regression and feature engineering", "Several predictors, interactions, scaling",
     [("mlr", "essential", "Adding engineered features means reading each coefficient with the others held fixed."),
      ("slr", "essential", "Every multiple-regression idea extends the one-predictor line.")]),
    (5, "Gradient descent", "Loss functions and following the slope downhill",
     [("chain-rule", "essential", "Gradient descent steps along the derivative of the loss, computed with the chain rule."),
      ("slr", "helpful", "The first loss we minimize is the squared error of a regression line.")]),
    (6, "Classification with logistic regression", "Log-odds, the logistic curve, decision thresholds",
     [("logs", "essential", "The logistic function and log-odds turn a straight line into a probability."),
      ("probability", "essential", "Predictions are probabilities that you threshold into classes.")]),
    (7, "Naive Bayes", "Conditional independence and text classification",
     [("probability", "essential", "Naive Bayes multiplies the conditional probability of each feature given the class."),
      ("logs", "helpful", "Products of many small probabilities are added as logs to avoid underflow.")]),
    (8, "Vectors, similarity and embeddings", "Representing items as vectors; nearest neighbors",
     [("dot-product", "essential", "Similarity between embeddings is a dot product (cosine similarity).")]),
    (9, "Neural networks as stacked layers", "Neurons, layers, activations",
     [("matmul", "essential", "Each layer computes Wx + b, a matrix multiplication, so shapes must line up."),
      ("dot-product", "helpful", "A single neuron is a dot product followed by an activation.")]),
    (10, "Backpropagation", "Computing gradients through a network",
     [("chain-rule", "essential", "Backpropagation applies the chain rule layer by layer."),
      ("matmul", "helpful", "Gradients for a layer are matrix products of upstream gradients and inputs.")]),
    (11, "Evaluating models honestly", "Cross-validation, confusion matrices, calibration",
     [("probability", "helpful", "Precision, recall and calibration are conditional probabilities."),
      ("desc-stats", "helpful", "Cross-validation reports a mean and spread of scores.")]),
    (12, "Team project kickoff", "Shared repository, branches, code review",
     [("git", "essential", "Teams share code in a Git repository with branches and merges.")]),
    (13, "Storing and querying results", "Saving experiments to a small database",
     [("sql", "essential", "Experiment results go into tables you query with SQL.")]),
    (14, "Project presentations", "Final demos", []),
]

# How hard each concept is for the simulated class: (share who say they never studied it, first-try accuracy)
DIFFICULTY = {
    "python": (0.08, 0.85), "desc-stats": (0.04, 0.80), "slr": (0.12, 0.55), "mlr": (0.30, 0.45),
    "chain-rule": (0.42, 0.30), "logs": (0.20, 0.50), "probability": (0.08, 0.65),
}


def term_start(today: date) -> date:
    """Monday of week 1, placing today in week 4."""
    return today - timedelta(days=today.weekday()) - timedelta(weeks=3)


def syllabus_text(start: date) -> str:
    """The sample as a syllabus, for exercising the real parsing pipeline."""
    rows = "\n".join(f"| Week {w} | {(start + timedelta(weeks=w - 1)).isoformat()} | {t} | {d} |" for w, t, d, _ in SCHEDULE)
    return f"""# {CODE}: {TITLE}
Sample syllabus (fictional), Fall {start.year}.

Prerequisite: {PREREQ}
No calculus or linear algebra background is required.

AI policy: generative AI may be used to explain concepts; graded work must be your own.

## Schedule
| Week | Date | Topic | Details |
|---|---|---|---|
{rows}
"""


def create_sample(ctx: Ctx, owner: str, simulate: bool = True) -> Course:
    today = ctx.now().date()
    start = term_start(today)
    course = Course(
        owner=owner, code=CODE, title=TITLE, term=f"Sample term {start.year}", term_start=start,
        term_end=start + timedelta(weeks=14), official_prereqs=["DEMO 212"], prereq_text=PREREQ,
        prereq_routes=["or equivalent", "permission of the instructor"],
        instructor_notes=["No calculus or linear algebra background is required."],
        ai_policy=AiPolicy(stance="limited", summary="Generative AI may be used to explain concepts; graded work must be your own."),
        timeline_kind="weeks", bulletin=BULLETIN, demo=True,
        prereq_docs=[PrereqDoc(code="DEMO 212", text=DEMO_212_SYLLABUS)],
        syllabus_text=syllabus_text(start),
    )
    repo = ctx.course(course.id)

    concepts: dict[str, Concept] = {}
    questions: list[BankQuestion] = []
    for key in dict.fromkeys(k for *_, reqs in SCHEDULE for k, _, _ in reqs):
        lib = library.BY_KEY[key]
        concepts[key] = Concept(
            name=lib.name, summary=lib.summary, depth=lib.depth,
            refresh_minutes=lib.refresh_minutes, learn_minutes=lib.learn_minutes, refresher=lib.refresher,
            learn_outline=lib.learn_outline,
            resources=[Resource(title=r.title, url=r.url, detail=r.detail) for r in (library.RESOURCES_BY_ID[i] for i in lib.resources)],
        )
        for order, q in enumerate(lib.questions):
            choices, idx = library.placed_choices(q, key)
            questions.append(BankQuestion(concept_id=concepts[key].id, prompt=q.prompt, choices=choices, correct_index=idx,
                                          explanation=q.explanation, status="approved", origin="sample", order=order))
    topics, reqs = [], []
    for week, title, details, needs in SCHEDULE:
        t = Topic(week=week, title=title, details=details)  # week-level: dates come from the term start
        topics.append(t)
        reqs += [Requirement(topic_id=t.id, concept_id=concepts[k].id, importance=imp, how_used=how) for k, imp, how in needs]

    # Prerequisite relations from the library, kept acyclic and direct.
    keys = list(concepts)
    candidates = [(keys.index(f), keys.index(k), 1.0) for k in keys for f in library.BUILDS_ON.get(k, ()) if f in concepts]
    dag, _ = acyclic_edges(candidates)
    edges = [Edge(src=concepts[keys[s]].id, dst=concepts[keys[d]].id) for s, d, _ in transitive_reduction(dag)]

    # The real evidence stage, with the offline engine: coverage is computed from DEMO 212's syllabus and the notes.
    from ..mapping import CountingEngine, Run, check_coverage, coverage_notes

    run = Run(ctx=ctx, course=course, engine=CountingEngine(OfflineEngine()))
    run.trace.append(StageTrace(stage="Sample course", notes=["Timeline, concepts and questions are hand-written (fictional course)."]))
    with run.stage("Checking what prerequisites taught") as st:
        st.notes = coverage_notes(check_coverage(run, list(concepts.values())))
    course.build.status, course.build.stage, course.build.trace = "ready", "Ready", run.trace

    with ctx.lock(course.id):
        repo.wipe()
        repo.topics.put_many(topics)
        repo.concepts.put_many(list(concepts.values()))
        repo.edges.put_many(edges)
        repo.requirements.put_many(reqs)
        repo.questions.put_many(questions)
    ctx.catalog.put(course)
    if simulate:
        simulate_class(ctx, course, concepts, questions)
    return course


def simulate_class(ctx: Ctx, course: Course, concepts: dict[str, Concept], questions: list[BankQuestion], n: int = 26) -> None:
    """Deterministic simulated students, so the class view isn't empty before real students join."""
    rng = random.Random(410)
    repo = ctx.course(course.id)
    bank: dict[str, list[BankQuestion]] = {}
    for q in sorted(questions, key=lambda q: q.order):
        bank.setdefault(q.concept_id, []).append(q)
    base = datetime.combine(ctx.now().date() - timedelta(days=6), time(15), tzinfo=timezone.utc)
    # Exact proportions per concept (not independent draws) so the class view tells a stable story.
    plan: dict[str, dict[int, str]] = {}
    for key, (p_never, p_first) in DIFFICULTY.items():
        order = list(range(n))
        rng.shuffle(order)
        n_never = round(p_never * n)
        rest = order[n_never:]
        n_right = round(p_first * len(rest))
        plan[key] = {i: "never" for i in order[:n_never]} | {i: "right" for i in rest[:n_right]} | {i: "wrong" for i in rest[n_right:]}

    enrollments, responses = [], []
    for i in range(n):
        sid = f"sim_{i:02d}"
        e = Enrollment(id=sid, route=rng.choice(["took_here"] * 3 + ["equivalent", "permission"]),
                       weekly_minutes=rng.choice([120, 180, 240, 300]), simulated=True)
        clock = base + timedelta(hours=i)
        for key in DIFFICULTY:
            cid = concepts[key].id
            outcome = plan[key][i]
            if outcome == "never":
                e.self_report[cid] = "never"
                continue
            e.self_report[cid] = "yes" if rng.random() < 0.8 else "unsure"
            qs = bank[cid]
            seq = [outcome == "right"]
            if seq[0] and rng.random() < 0.7:
                seq.append(rng.random() < 0.9)
            elif not seq[0] and rng.random() < 0.6:
                seq += [rng.random() < 0.75, rng.random() < 0.85]  # refreshed, then re-checked
            for j, ok in enumerate(seq):
                q = qs[j % len(qs)]
                wrong = next(k for k in range(4) if k != q.correct_index)
                clock += timedelta(minutes=3)
                responses.append(Response(student=sid, question_id=q.id, concept_id=cid, choice=q.correct_index if ok else wrong,
                                          correct=ok, phase="check" if j == 0 else "practice", at=clock, simulated=True))
        enrollments.append(e)
    repo.enrollments.put_many(enrollments)
    repo.responses.put_many(responses)

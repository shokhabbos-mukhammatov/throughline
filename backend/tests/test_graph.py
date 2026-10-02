"""Entity resolution, cycle-safe graph building, self-consistency voting and evidence checks."""

from datetime import date

from throughline.config import Settings
from throughline.ctx import Ctx
from throughline.graph import acyclic_edges, resolve, transitive_reduction
from throughline.llm.offline import OfflineEngine
from throughline.llm.schemas import (
    CoverageJudgment,
    CoverageJudgments,
    Foundation,
    ItemRequirements,
    MappingResult,
    PairJudgment,
    RequiredConcept,
    SameConceptJudgments,
)
from throughline.mapping import CountingEngine, Run, assemble, check_coverage, propose
from throughline.models import BulletinEntry, Concept, Course, PrereqDoc, Topic
from throughline.store.memory import MemoryStore
from throughline.textutil import hashed_embedding


class Scripted(OfflineEngine):
    """An 'online' engine with scripted answers, to test the pipeline's own logic."""

    online = True

    def __init__(self, vectors=None, same=(), mapping=None, coverage=None):
        self.vectors, self.same, self.mapping, self.coverage = vectors or {}, set(same), mapping or {}, coverage or {}
        self.asked = []

    def embed(self, texts):
        out = []
        for t in texts:
            v = self.vectors.get(t.split(":")[0].lower())
            out.append(v + [0.0] * (768 - len(v)) if v else hashed_embedding(t))
        return out

    def judge_same(self, pairs):
        self.asked += [(p.a_name, p.b_name) for p in pairs]
        return SameConceptJudgments(judgments=[PairJudgment(pair_id=p.pair_id, same=frozenset((p.a_name.lower(), p.b_name.lower())) in self.same)
                                               for p in pairs])

    def map_prerequisites(self, ctx, items, known, sample=0):
        return MappingResult(items=[ItemRequirements(item_id=it.id, requires=self.mapping.get(sample, {}).get(it.title, [])) for it in items])

    def judge_coverage(self, requests):
        return CoverageJudgments(judgments=[self.coverage.get(r.name, CoverageJudgment(concept_id=r.concept_id, verdict="unrelated")).model_copy(update={"concept_id": r.concept_id}) for r in requests])


def req(name, *foundations, covered_by=None):
    return RequiredConcept(name=name, summary=f"{name} summary", importance="essential", how_used="used", depth="d",
                           covered_by=covered_by, builds_on=[Foundation(name=f, summary="") for f in foundations])


def test_resolution_uses_library_embeddings_and_the_judge():
    vectors = {
        "mean and variance": [1, 0, 0, 0], "means and variances": [1, 0, 0, 0],  # identical vectors: merged by embedding
        "least squares regression": [0, 1, 0.6, 0], "linear regression basics": [0, 0.6, 1, 0],  # cosine 0.88: asked
        "hash tables": [0, 0, 0, 1],
    }
    engine = Scripted(vectors={k: v for k, v in vectors.items()}, same={frozenset(("least squares regression", "linear regression basics"))})
    names = [("Mean and Variance", ""), ("Means and Variances", ""), ("Least Squares Regression", ""), ("Linear Regression Basics", ""),
             ("Hash Tables", ""), ("Descriptive Statistics", ""), ("descriptive statistics", "")]
    res = resolve(engine, names)
    of = lambda n: res.cluster_of(n).id
    assert of("Mean and Variance") == of("Means and Variances")
    assert of("Least Squares Regression") == of("Linear Regression Basics") and res.stats["judged_same"] == 1
    assert ("Least Squares Regression", "Linear Regression Basics") in engine.asked, "the judge sees real names"
    assert of("Hash Tables") != of("Least Squares Regression")
    assert of("Descriptive Statistics") == of("descriptive statistics")
    assert res.cluster_of("Descriptive Statistics").name == "Descriptive Statistics"


def test_graph_drops_cycles_and_indirect_edges():
    kept, dropped = acyclic_edges([(0, 1, 1.0), (1, 2, 0.9), (2, 0, 0.5), (0, 2, 0.4)])
    assert dropped == 1 and (2, 0, 0.5) not in kept
    reduced = transitive_reduction(kept)
    assert (0, 2, 0.4) not in reduced and len(reduced) == 2


def make_run(engine, course=None, store=None):
    store = store or MemoryStore()
    course = course or Course(owner="me", code="DS 612", official_prereqs=["DS 212"])
    ctx = Ctx(store=store, engine=engine, settings=Settings(offline=False, bulletin_live=False, mapping_samples=3, gemini_api_key="k"))
    ctx.catalog.put(course)
    return Run(ctx=ctx, course=course, engine=CountingEngine(engine))


def test_self_consistency_keeps_majority_concepts_and_edges():
    t1 = Topic(week=4, date=date(2026, 9, 15), title="Quiz 1")
    mapping = {
        0: {"Quiz 1": [req("Multiple Regression", "Simple Regression"), req("Matrix Calculus")]},
        1: {"Quiz 1": [req("Multiple Regression", "Simple Regression")]},
        2: {"Quiz 1": [req("Multiple Regression")]},
    }
    engine = Scripted(mapping=mapping)
    run = make_run(engine)
    proposals = propose(run, [t1], [])
    assert {p.sample for p in proposals} == {0, 1, 2} and run.engine.calls["map_prerequisites"] == 3
    concepts, reqs, edges, stats = assemble(run, proposals, [t1])
    names = {c.name: c for c in concepts}
    assert "Matrix Calculus" not in names, "proposed by 1 of 3 runs: dropped"
    assert names["Multiple Regression"].confidence == 1.0
    assert names["Simple Regression"].foundation and len(edges) == 1, "edge proposed by 2 of 3 runs: kept"
    assert stats["runs"] == 3 and len(reqs) == 1


def test_coverage_requires_a_real_quote_from_a_listed_prerequisite():
    course = Course(owner="me", code="DS 612", official_prereqs=["DS 212"],
                    bulletin=[BulletinEntry(code="DS 212", title="Business Statistics", description="Estimation, tests of hypotheses, and regression analysis.")],
                    instructor_notes=["You do not need linear algebra for this course."])
    concepts = [Concept(name="Simple Linear Regression"), Concept(name="Hypothesis Testing"), Concept(name="Matrix Multiplication"),
                Concept(name="Python Fundamentals", covered_by="DS 212")]
    coverage = {
        "Simple Linear Regression": CoverageJudgment(concept_id="", verdict="teaches", passage="p1", quote="tests of hypotheses, and regression analysis"),
        "Hypothesis Testing": CoverageJudgment(concept_id="", verdict="teaches", passage="p1", quote="a full unit on hypothesis testing with t-tests"),
    }
    run = make_run(Scripted(coverage=coverage), course)
    stats = check_coverage(run, concepts)
    by = {c.name: c for c in concepts}
    assert by["Simple Linear Regression"].coverage == "listed" and by["Simple Linear Regression"].covered_by == "DS 212"
    assert by["Hypothesis Testing"].coverage != "listed" and stats["rejected_quotes"] == 1, "fabricated quote is rejected"
    assert by["Matrix Multiplication"].coverage == "missing" and "do not need" in by["Matrix Multiplication"].evidence
    assert by["Python Fundamentals"].coverage == "likely", "model knowledge alone is only 'likely'"


def test_prerequisite_syllabus_turns_unknown_into_missing():
    course = Course(owner="me", code="DS 612", official_prereqs=["DS 212"],
                    bulletin=[BulletinEntry(code="DS 212", title="Business Statistics", description="Statistical methods.")])
    concepts = [Concept(name="Logistic Regression")]
    check_coverage(make_run(OfflineEngine(), course), concepts)
    assert concepts[0].coverage == "unknown", "a vague Bulletin line isn't evidence either way"
    course.prereq_docs = [PrereqDoc(code="DS 212", text="Week 1: Descriptive statistics\nWeek 9: Simple linear regression")]
    concepts = [Concept(name="Logistic Regression"), Concept(name="Simple Linear Regression")]
    check_coverage(make_run(OfflineEngine(), course), concepts)
    assert concepts[0].coverage == "missing" and "Not found in the DS 212 syllabus" in concepts[0].evidence
    assert concepts[1].coverage == "listed" and "Week 9" in concepts[1].evidence

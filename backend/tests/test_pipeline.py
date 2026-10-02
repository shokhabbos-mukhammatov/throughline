"""The real build pipeline, run with the offline engine on syllabus layouts seen in practice."""

from datetime import timedelta

from throughline import bulletin
from throughline.mapping import build_course
from throughline.models import Course
from throughline.seed import sample
from throughline.textutil import redact


def concepts_by_id(repo):
    return {c.id: c.name for c in repo.concepts.list()}


def build(ctx, text, code=""):
    course = Course(owner="me", code=code, syllabus_text=redact(text))
    ctx.catalog.put(course)
    build_course(ctx, course.id, code)
    return ctx.catalog.get(course.id), ctx.course(course.id)


def test_sample_syllabus_builds_a_map(ctx):
    start = sample.term_start(ctx.now().date())
    course, repo = build(ctx, sample.syllabus_text(start), "DEMO 410")
    assert course.build.status == "ready", course.build.error
    assert course.timeline_kind == "dated_weeks" and course.term_start == start
    assert len(repo.topics.list()) == 14
    names = {c.name for c in repo.concepts.list()}
    assert {"Derivatives and the Chain Rule", "Matrix Multiplication", "Version Control with Git"} <= names
    concepts = {c.name: c for c in repo.concepts.list()}
    edges = {(concepts_by_id(repo)[e.src], concepts_by_id(repo)[e.dst]) for e in repo.edges.list()}
    assert ("Simple Linear Regression", "Multiple Linear Regression") in edges
    assert concepts["Derivatives and the Chain Rule"].coverage == "missing", "the syllabus says no calculus is required"
    assert course.prereq_routes and "DEMO 212" in course.official_prereqs
    assert course.ai_policy.stance == "limited"
    qs = repo.questions.list()
    assert qs and all(len(q.choices) == 4 for q in qs)
    assert len({q.correct_index for q in qs}) > 1, "answer positions should vary"


def test_dated_table_without_week_word(ctx):
    text = """CSC 999 Example Course    Spring 2026
Prerequisites: CSC 101 with grades of C or better.
Tentative Schedule:
 Week   Date (Wed)     Topic
  1       Jan 28       Introduction to the Course
  2       Feb 4        Version Control Basics (Git) and team workflow
  3       Feb 11       Conceptual Design of Database Systems
  4       Feb 18       Spring Break (No Classes)
  5       Feb 25       Backend design with SQL queries
"""
    course, repo = build(ctx, text, "CSC 999")
    assert course.build.status == "ready", course.build.error
    titles = [t.title for t in sorted(repo.topics.list(), key=lambda t: t.week)]
    assert titles[0].startswith("Introduction") and not any("Break" in t for t in titles)
    weeks = {t.week: t for t in repo.topics.list()}
    assert weeks[2].date - weeks[1].date == timedelta(weeks=1)
    assert {"Version Control with Git", "Relational Databases and SQL"} <= {c.name for c in repo.concepts.list()}
    # No Bulletin text or syllabus for CSC 101: nothing confirms coverage, and nothing rules it out.
    assert {c.coverage for c in repo.concepts.list()} == {"unknown"} and not any(c.hidden for c in repo.concepts.list())
    trace = {t.stage: t for t in course.build.trace}
    assert "Resolving concepts and building the graph" in trace and trace["Reading the syllabus"].calls == {"parse_syllabus": 1}


def test_assessment_only_syllabus(ctx):
    text = """BUS 777 Analytics Sample   Fall 2026
Prerequisites: BUS 100 or equivalent with a grade of C- or better.
Quiz dates
Quiz 1 · Sep 15
Statistics refresher, Python fundamentals, simple linear regression
Quiz 2 · Sep 29
Multiple linear regression, the confusion matrix
"""
    course, repo = build(ctx, text, "BUS 777")
    assert course.build.status == "ready", course.build.error
    assert course.timeline_kind == "assessments"
    topics = repo.topics.list()
    assert {t.kind for t in topics} == {"assessment"} and all(t.date for t in topics)
    assert "or equivalent" in course.prereq_routes
    assert "Simple Linear Regression" in {c.name for c in repo.concepts.list()}


def test_no_schedule_fails_clearly(ctx):
    course, _ = build(ctx, "MATH 000 Example. Prerequisite: MATH 001. We will cover chapters 1-9 of the textbook." * 3, "MATH 000")
    assert course.build.status == "error" and "schedule" in course.build.error


def test_bulletin_snapshot_marks_coverage(ctx, monkeypatch):
    monkeypatch.setitem(bulletin.SNAPSHOT, "STAT 100", bulletin.BulletinEntry(
        code="STAT 100", title="Intro Stats", description="Descriptive statistics, probability and simple linear regression.",
        prerequisites="None."))
    text = "SCI 300 Sample  Fall 2026\nPrerequisite: STAT 100.\nWeek 1 (2026-08-24): Regression review\nWeek 2 (2026-08-31): Gradient and chain rule\n"
    course, repo = build(ctx, text, "SCI 300")
    by_name = {c.name: c for c in repo.concepts.list()}
    assert by_name["Simple Linear Regression"].covered_by == "STAT 100" and by_name["Simple Linear Regression"].coverage == "listed"
    assert by_name["Derivatives and the Chain Rule"].coverage == "unknown", "a short Bulletin line can't rule it out"


def test_redaction():
    text = "Instructor: Jane Q Doe   Email: jdoe@sfsu.edu\nPhone: (415) 338-6299\nDear Dr. El Alaoui, see https://sfsu.instructure.com/courses/1"
    out = redact(text)
    assert "jdoe@" not in out and "338-6299" not in out and "Jane" not in out and "Alaoui" not in out
    assert "instructure" not in out and "[email]" in out


def test_bulletin_parser_reads_courseleaf_blocks():
    html = """<div class="courseblock"><p class="courseblocktitle"><strong>DS&#160;612 Data Mining with Business Applications (Units: 3)</strong></p>
    <p class="courseblockdesc">Prerequisites: DS 212/ECON 212 or equivalent. Concepts of modeling complex datasets.</p></div>
    <div class="courseblock"><p class="courseblocktitle"><strong>DS 212 Business Statistics (Units: 3)</strong></p>
    <p class="courseblockdesc">Prerequisite: MATH 110 with grade of C- or better. Statistical methods including regression analysis.</p></div>"""
    entries = bulletin.parse_subject_page(html, "DS")
    assert entries["DS 612"].title == "Data Mining with Business Applications"
    assert entries["DS 612"].prereq_codes == ["DS 212", "ECON 212"]
    assert "regression" in entries["DS 212"].description

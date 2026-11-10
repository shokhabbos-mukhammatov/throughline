"""Several prerequisites per course, alternatives ("A or B"), and the courses a student actually took, at any school."""

import json

import pytest
from fastapi.testclient import TestClient

from throughline import api, bulletin
from throughline.background import Background, effective_met, unanswered_choices
from throughline.mapping import build_course
from throughline.models import Course, Enrollment, PriorCourse
from throughline.readiness import Snapshot, concept_view
from throughline.seed import sample
from throughline.textutil import prereq_groups, redact, tidy_groups

client = TestClient(api.app)

STAT = bulletin.BulletinEntry(code="STAT 100", title="Intro Stats", prerequisites="None.",
                              description="Descriptive statistics, probability and simple linear regression.")
CALC = bulletin.BulletinEntry(code="MATH 200", title="Calculus", prerequisites="None.",
                              description="Limits, derivatives and the chain rule, integrals.")
WEEKS = "Week 1 (2026-08-24): Regression review\nWeek 2 (2026-08-31): Gradient and chain rule\n"
# An equivalent course from another school: it teaches regression, not descriptive statistics.
CSE_206 = """CSE 206 Machine Learning Foundations, Riverbend University
Instructor: Dr. Someone  Email: someone@riverbend.example
Week 1: Vectors and the dot product
Week 3: Simple linear regression: fitting a line and reading its slope
Week 5: Derivatives and the chain rule for gradient descent
"""


@pytest.fixture
def two_courses(monkeypatch):
    monkeypatch.setitem(bulletin.SNAPSHOT, "STAT 100", STAT)
    monkeypatch.setitem(bulletin.SNAPSHOT, "MATH 200", CALC)


def build(ctx, prerequisite_line):
    course = Course(owner="me", code="SCI 300", syllabus_text=redact(f"SCI 300 Sample  Fall 2026\n{prerequisite_line}\n{WEEKS}"))
    ctx.catalog.put(course)
    build_course(ctx, course.id, "SCI 300")
    course = ctx.catalog.get(course.id)
    assert course.build.status == "ready", course.build.error
    return course, ctx.course(course.id)


def seen_by(ctx, course, repo, name, **enrollment):
    repo.enrollments.put(Enrollment(id="s", **enrollment))
    snap = Snapshot.load(course, repo, "s", ctx.now().date())
    c = next(c for c in snap.concepts.values() if c.name == name)
    return concept_view(snap, c), float(snap.model.prior[snap.model.ids.index(c.id)])


@pytest.mark.parametrize("text, codes, groups", [
    ("DS 212/ECON 212 or equivalent; ISYS 263 or passing the waiver exam. DS 311 and/or DS 312 recommended.",
     ["DS 212", "ECON 212", "ISYS 263"], [["DS 212", "ECON 212"], ["ISYS 263"]]),
    ("DS 110 or MATH 108 or MATH 110 or MATH 226 with grades of C- or better.",
     ["DS 110", "MATH 108", "MATH 110", "MATH 226"], [["DS 110", "MATH 108", "MATH 110", "MATH 226"]]),
    ("Upper-division standing; CSC 317 and CSC 413 with grades of C or better; or permission of the instructor.",
     ["CSC 317", "CSC 413"], [["CSC 317"], ["CSC 413"]]),
    ("CSC 220, CSC 230, and MATH 227", ["CSC 220", "CSC 230", "MATH 227"], [["CSC 220"], ["CSC 230"], ["MATH 227"]]),
    ("MATH 226, MATH 227, or MATH 228", ["MATH 226", "MATH 227", "MATH 228"], [["MATH 226", "MATH 227", "MATH 228"]]),
    ("CSC 340 and (MATH 324 or MATH 338)", ["CSC 340", "MATH 324", "MATH 338"], [["CSC 340"], ["MATH 324", "MATH 338"]]),
    ("MATH 226 or MATH 227, CSC 210 or CSC 220", ["MATH 226", "MATH 227", "CSC 210", "CSC 220"], [["MATH 226", "MATH 227"], ["CSC 210", "CSC 220"]]),
    ("", ["CSC 317", "CSC 413"], [["CSC 317"], ["CSC 413"]]),
])
def test_a_prerequisite_statement_becomes_required_groups_with_alternatives(text, codes, groups):
    assert prereq_groups(text, codes) == groups


def test_proposed_groups_keep_only_listed_courses_and_lose_none():
    statement = "DS 212/ECON 212 or equivalent; ISYS 263"
    assert tidy_groups([["ds212", "ECON 212"], ["XX 999"]], ["DS 212", "ECON 212", "ISYS 263"], statement) == [["DS 212", "ECON 212"], ["ISYS 263"]]
    assert tidy_groups([], ["DS 212", "ECON 212", "ISYS 263"], statement) == [["DS 212", "ECON 212"], ["ISYS 263"]]


def test_a_course_with_two_required_prerequisites_checks_each_one(ctx, two_courses):
    course, repo = build(ctx, "Prerequisites: STAT 100 and MATH 200.")
    assert course.prereq_groups == [["STAT 100"], ["MATH 200"]]
    by_name = {c.name: c for c in repo.concepts.list()}
    slr, chain = by_name["Simple Linear Regression"], by_name["Derivatives and the Chain Rule"]
    assert (slr.coverage, slr.covered_by) == ("listed", "STAT 100") and (chain.coverage, chain.covered_by) == ("listed", "MATH 200")
    assert {r.code: r.coverage for r in slr.by_course} == {"STAT 100": "listed", "MATH 200": "unknown"}
    assert {r.code: r.coverage for r in chain.by_course} == {"STAT 100": "unknown", "MATH 200": "listed"}
    assert next(r for r in chain.by_course if r.code == "MATH 200").quote, "every 'taught there' carries its quote"

    # A student who took both sees both as taught; one who skipped calculus has a gap exactly there.
    both = {"STAT 100": "took", "MATH 200": "took"}
    assert seen_by(ctx, course, repo, chain.name, met=both)[0]["covered_by"] == "MATH 200"
    view, prior = seen_by(ctx, course, repo, chain.name, met={"STAT 100": "took", "MATH 200": "none"})
    assert view["coverage"] == "gap" and view["covered_by"] is None and "MATH 200 teaches it" in view["coverage_note"]
    assert prior < seen_by(ctx, course, repo, chain.name, met=both)[1]
    assert seen_by(ctx, course, repo, slr.name, met={"STAT 100": "took", "MATH 200": "none"})[0]["coverage"] == "listed"


def test_with_alternatives_coverage_follows_the_one_the_student_took(ctx, two_courses):
    course, repo = build(ctx, "Prerequisite: STAT 100 or MATH 200.")
    assert course.prereq_groups == [["STAT 100", "MATH 200"]]
    slr, chain = "Simple Linear Regression", "Derivatives and the Chain Rule"
    took_stats = {"STAT 100": "took", "MATH 200": "none"}
    took_calc = {"STAT 100": "none", "MATH 200": "took"}

    assert seen_by(ctx, course, repo, slr, met=took_stats)[0]["covered_by"] == "STAT 100"
    view, prior = seen_by(ctx, course, repo, slr, met=took_calc)
    assert view["coverage"] == "unknown" and view["covered_by"] is None
    assert "STAT 100 teaches it" in view["coverage_note"] and "MATH 200, which you took" in view["coverage_note"]
    assert prior < seen_by(ctx, course, repo, slr, met=took_stats)[1]
    assert seen_by(ctx, course, repo, chain, met=took_calc)[0]["covered_by"] == "MATH 200"
    assert seen_by(ctx, course, repo, chain, met={"STAT 100": "took", "MATH 200": "took"})[0]["coverage"] == "listed", "took both"
    # Before the student has said anything, they see the course-level answer.
    assert seen_by(ctx, course, repo, slr)[0]["covered_by"] == "STAT 100"

    # With a syllabus for the alternative they took, "not confirmed" becomes a definite gap.
    course.prereq_docs = [api.PrereqDoc(code="MATH 200", text="Week 1: Limits\nWeek 2: Derivatives and the chain rule\nWeek 3: Integrals")]
    ctx.catalog.put(course)
    from throughline.mapping import recheck_coverage
    recheck_coverage(ctx, course.id)
    course = ctx.catalog.get(course.id)
    view, _ = seen_by(ctx, course, repo, slr, met=took_calc)
    assert view["coverage"] == "gap" and "isn't in the MATH 200 syllabus" in view["coverage_note"]


def test_records_from_before_per_course_answers_are_still_understood(ctx):
    course = sample.create_sample(ctx, "owner")
    course.official_prereqs, course.prereq_groups = ["DEMO 212", "MATH 108"], [["DEMO 212", "MATH 108"]]
    groups = course.groups()
    assert effective_met(Enrollment(id="s", route="took_here", prereq_taken="MATH 108"), groups) == {"DEMO 212": "none", "MATH 108": "took"}
    assert effective_met(Enrollment(id="s", route="equivalent"), groups) == {"DEMO 212": "elsewhere", "MATH 108": "elsewhere"}
    assert effective_met(Enrollment(id="s", route="permission"), groups) == {"DEMO 212": "none", "MATH 108": "none"}
    assert effective_met(Enrollment(id="s"), groups) == {}
    assert unanswered_choices(course, Enrollment(id="s")) == [["DEMO 212", "MATH 108"]]
    assert unanswered_choices(course, Enrollment(id="s", met={"MATH 108": "took"})) == []

    repo = ctx.course(course.id)
    view_212, prior_212 = seen_by(ctx, course, repo, "Descriptive Statistics", route="took_here", prereq_taken="DEMO 212")
    view_108, prior_108 = seen_by(ctx, course, repo, "Descriptive Statistics", route="took_here", prereq_taken="MATH 108")
    assert view_212["coverage"] == "listed" and view_212["covered_by"] == "DEMO 212"
    assert view_108["coverage"] == "unknown" and view_108["covered_by"] is None and prior_212 > prior_108

    # A course mapped before groups were stored gets them from its prerequisite sentence.
    old = Course(owner="o", official_prereqs=["CSC 317", "CSC 413"], prereq_text="CSC 317 and CSC 413 with grades of C or better")
    assert old.groups() == [["CSC 317"], ["CSC 413"]] and old.public()["prereq_groups"] == [["CSC 317"], ["CSC 413"]]


def test_the_quick_check_waits_until_alternatives_are_answered():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-b1"}).json()
    cid, me = course["id"], {"X-Demo-User": "stu-b1"}
    assert course["prereq_groups"] == [["DEMO 212"]]
    assert client.post(f"/api/courses/{cid}/check/next", json={"session": []}, headers=me).status_code == 200, "nothing to choose"

    stored = api.services.catalog.get(cid)
    stored.official_prereqs, stored.prereq_groups = ["DEMO 212", "DEMO 110", "DEMO 115"], [["DEMO 212"], ["DEMO 110", "DEMO 115"]]
    api.services.catalog.put(stored)
    detail = client.get(f"/api/courses/{cid}", headers=me).json()
    assert detail["choices_needed"] == [["DEMO 110", "DEMO 115"]]
    blocked = client.post(f"/api/courses/{cid}/check/next", json={"session": []}, headers=me)
    assert blocked.status_code == 409 and "DEMO 110 or DEMO 115" in blocked.json()["detail"]

    # Answers saved from the add-course form don't finish setup; saving setup does.
    saved = client.put(f"/api/courses/{cid}/me", json={"met": {"demo 110": "took", "DEMO 115": "none", "DEMO 212": "bogus"}, "draft": True}, headers=me).json()
    assert saved["met"] == {"DEMO 110": "took", "DEMO 115": "none"} and saved["route"] == "took_here"
    detail = client.get(f"/api/courses/{cid}", headers=me).json()
    assert detail["choices_needed"] == [] and not detail["enrolled"] and detail["enrollment"]["met"]["DEMO 110"] == "took"
    assert client.post(f"/api/courses/{cid}/check/next", json={"session": []}, headers=me).status_code == 200
    client.put(f"/api/courses/{cid}/me", json={"weekly_minutes": 120}, headers=me)
    assert client.get(f"/api/courses/{cid}", headers=me).json()["enrolled"]


def test_a_course_from_another_school_counts_through_its_own_syllabus():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-b2"}).json()
    cid, me, other = course["id"], {"X-Demo-User": "stu-b2"}, {"X-Demo-User": "stu-b3"}
    url = f"/api/courses/{cid}/background"
    client.put(f"/api/courses/{cid}/me", json={"met": {"DEMO 212": "elsewhere"}}, headers=me)

    def concepts():
        return {c["name"]: c for c in client.get(f"/api/courses/{cid}", headers=me).json()["concepts"]}

    before = concepts()
    assert before["Simple Linear Regression"]["coverage"] == "unknown"
    assert "add the syllabus of the course you took instead" in before["Simple Linear Regression"]["coverage_note"]

    r = client.post(url, headers=me, data={"code": "cse206", "school": "Riverbend University", "replaces": "DEMO 212", "text": CSE_206})
    assert r.status_code == 200, r.text
    added = r.json()
    assert added["code"] == "CSE 206" and added["school"] == "Riverbend University" and added["has_syllabus"] and added["source"] == "pasted text"
    assert {c["name"] for c in added["covers"]} >= {"Simple Linear Regression", "Derivatives and the Chain Rule"}
    assert "someone@riverbend.example" not in json.dumps(added) and "chunks" not in added, "the syllabus text never comes back"

    after = concepts()
    slr, desc, chain = after["Simple Linear Regression"], after["Descriptive Statistics"], after["Derivatives and the Chain Rule"]
    assert slr["coverage"] == "listed" and slr["covered_by"] == "CSE 206 (Riverbend University)"
    assert desc["coverage"] == "gap" and "DEMO 212 teaches it" in desc["coverage_note"] and "CSE 206 (Riverbend University) syllabus" in desc["coverage_note"]
    assert chain["coverage"] == "listed", "their course taught what this class's listed prerequisite doesn't"
    assert chain["p"] > before["Derivatives and the Chain Rule"]["p"] and desc["p"] < before["Descriptive Statistics"]["p"]
    study = client.get(f"/api/courses/{cid}/concepts/{slr['id']}", headers=me).json()
    assert study["your_evidence"][0]["source"] == "Your CSE 206 (Riverbend University) syllabus" and "regression" in study["your_evidence"][0]["quote"].lower()
    assert any(r["code"] == "DEMO 212" for r in study["by_course"])

    # Private to the student, and gone with their data.
    assert client.get(url, headers=other).json() == []
    assert client.delete(f"{url}/{added['id']}", headers=other).status_code == 404
    theirs = {c["name"]: c for c in client.get(f"/api/courses/{cid}", headers=other).json()["concepts"]}
    assert theirs["Simple Linear Regression"]["covered_by"] == "DEMO 212"
    assert client.delete(f"/api/courses/{cid}/me", headers=me).json()["deleted_courses"] == 1
    assert client.get(url, headers=me).json() == []


def test_earlier_courses_take_a_file_or_no_syllabus_at_all():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-b4"}).json()
    url, me = f"/api/courses/{course['id']}/background", {"X-Demo-User": "stu-b4"}
    named = client.post(url, headers=me, data={"code": "Statistics 1", "school": "City College"}).json()
    assert named["code"] == "Statistics 1" and not named["has_syllabus"] and named["covers"] == [] and named["checked"] == 0
    filed = client.post(url, headers=me, data={"code": "MATH 51"}, files={"file": ("calc.txt", CSE_206.encode(), "text/plain")}).json()
    assert filed["source"] == "calc.txt" and filed["checked"] > 0 and filed["replaces"] is None
    assert client.post(url, headers=me, data={"code": "X"}).status_code == 400
    assert client.post(url, headers=me, data={"code": "OLD 100"}, files={"file": ("old.doc", b"binary", "application/msword")}).status_code == 415
    assert client.post(url, headers=me, data={"code": "EMPTY 100"}, files={"file": ("empty.txt", b"   ", "text/plain")}).status_code == 422
    assert [p["code"] for p in client.get(url, headers=me).json()] == ["Statistics 1", "MATH 51"]


def test_syllabi_added_before_the_map_exists_are_matched_when_it_is_built(ctx, two_courses):
    course = Course(owner="me", code="SCI 300", syllabus_text=redact(f"SCI 300 Sample  Fall 2026\nPrerequisite: STAT 100.\n{WEEKS}"))
    ctx.catalog.put(course)
    repo = ctx.course(course.id)
    from throughline.background import syllabus_chunks
    repo.prior_courses.put(PriorCourse(student="s", code="CSE 206", school="Riverbend University", replaces="STAT 100",
                                       source="pasted text", chunks=syllabus_chunks(CSE_206)))
    build_course(ctx, course.id, "SCI 300")
    prior = repo.prior_courses.list(student="s")[0]
    names = {c.id: c.name for c in repo.concepts.list()}
    assert {names[m.concept_id] for m in prior.matches} == {"Simple Linear Regression", "Derivatives and the Chain Rule"}
    assert set(prior.checked) == set(names)
    assert all("someone@riverbend.example" not in ch.text for ch in prior.chunks)
    course = ctx.catalog.get(course.id)
    assert "Checking the courses students took" in [t.stage for t in course.build.trace]
    view, _ = seen_by(ctx, course, repo, "Derivatives and the Chain Rule", met={"STAT 100": "elsewhere"})
    assert view["covered_by"] == "CSE 206 (Riverbend University)"


def test_a_course_takes_several_prerequisite_syllabi_as_files_or_text():
    owner = {"X-Demo-User": "owner-b5"}
    start = sample.term_start(api.services.now().date())
    listed = [{"code": "demo 212", "text": sample.DEMO_212_SYLLABUS}, {"code": "DEMO 110", "file": 0}]
    r = client.post("/api/courses", headers=owner, data={"code": "DEMO 410", "text": sample.syllabus_text(start), "prereqs": json.dumps(listed)},
                    files=[("prereq_files", ("demo110.txt", b"DEMO 110 Programming\nWeek 1: Python variables, loops and functions\n", "text/plain"))])
    assert r.status_code == 200, r.text
    assert r.json()["prereq_docs"] == ["DEMO 212", "DEMO 110"]
    assert client.post("/api/courses", headers=owner, data={"code": "DEMO 410", "text": sample.syllabus_text(start), "prereqs": "{}"}).status_code == 400

    pasted = client.post(f"/api/courses/{r.json()['id']}/prereq-syllabus", headers=owner,
                         data={"prereq_code": "DEMO 115", "text": "DEMO 115 Data analysis with R\nWeek 1: R basics and data frames\n"})
    assert pasted.status_code == 200 and pasted.json()["prereq_docs"] == ["DEMO 212", "DEMO 110", "DEMO 115"]
    assert client.post(f"/api/courses/{r.json()['id']}/prereq-syllabus", headers=owner, data={"prereq_code": "DEMO 115"}).status_code == 400


def test_bulletin_lookup_says_which_prerequisites_are_alternatives():
    entry = client.get("/api/bulletin/ds612").json()
    assert entry["prereq_groups"] == [["DS 212", "ECON 212"], ["ISYS 263"]]
    assert client.get("/api/bulletin/ds212").json()["prereq_groups"] == [["DS 110", "MATH 108", "MATH 110", "MATH 226"]]


def test_no_background_and_no_listed_prerequisites_fall_back_cleanly(ctx):
    course = sample.create_sample(ctx, "owner")
    repo = ctx.course(course.id)
    concepts = [c for c in repo.concepts.list() if not c.removed]
    plain = Background(course, Enrollment(id="s"), [])
    assert all(plain.of(c).coverage == c.coverage and plain.of(c).covered_by == c.covered_by for c in concepts)
    # Nobody took the listed prerequisite: what it teaches is a gap, what nothing teaches stays "not in listed prerequisites".
    waived = Background(course, Enrollment(id="s", met={"DEMO 212": "none"}), [])
    by_name = {c.name: waived.of(c) for c in concepts}
    assert by_name["Descriptive Statistics"].coverage == "gap" and "you didn't take it" in by_name["Descriptive Statistics"].note
    assert by_name["Derivatives and the Chain Rule"].coverage == "missing"


def test_a_weak_match_does_not_outweigh_the_instructor_saying_it_is_not_needed(ctx):
    from throughline.llm.offline import OfflineEngine
    from throughline.llm.schemas import CoverageJudgment, CoverageJudgments
    from throughline.mapping import CountingEngine, Run, check_coverage

    class EagerJudge(OfflineEngine):  # finds a "partial" match for everything, quoting the first passage it was shown
        def judge_coverage(self, requests):
            return CoverageJudgments(judgments=[
                CoverageJudgment(concept_id=r.concept_id, verdict="partial", passage=r.passages[0].label, quote=r.passages[0].text[:60])
                for r in requests])

    course = sample.create_sample(ctx, "owner")
    repo = ctx.course(course.id)
    concepts = repo.concepts.list()
    check_coverage(Run(ctx=ctx, course=course, engine=CountingEngine(EagerJudge())), concepts)
    by_name = {c.name: c for c in concepts}
    chain, stats = by_name["Derivatives and the Chain Rule"], by_name["Descriptive Statistics"]
    assert stats.coverage == "likely" and stats.by_course[0].coverage == "likely", "a weak match normally counts as 'probably'"
    assert chain.coverage == "missing" and "No calculus" in chain.evidence
    assert [r.coverage for r in chain.by_course] == ["missing"], "but not against 'no calculus background is required'"
    repo.concepts.put_many(concepts)
    view, _ = seen_by(ctx, course, repo, chain.name, met={"DEMO 212": "took"})
    assert view["coverage"] == "missing" and view["covered_by"] is None

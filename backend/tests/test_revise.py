"""The course owner correcting the map: a request, files from the course, a reviewed proposal, then apply."""

from fastapi.testclient import TestClient

from throughline import api, revise
from throughline.llm.offline import OfflineEngine
from throughline.llm.schemas import MapChange, NeedRef, RevisionPlan, SourceQuestion
from throughline.models import Revision
from throughline.readiness import Snapshot, plan
from throughline.seed import sample

client = TestClient(api.app)

STUDY_GUIDE = b"""Final exam study guide (fictional)
Week 11: ROC curves. You will compute the area under the curve, so review integration and area under a curve.
Office hours: email prof@school.example
"""
SAMPLE_EXAM = b"""Sample midterm questions (fictional)
1. Using the chain rule, what is the derivative of sin(x^2)?
A) cos(x^2)
B) 2x cos(x^2)
C) 2x sin(x)
D) cos(2x)
Answer: B
2. Which line is a course policy, not a question?
"""


def owner_course(owner: str) -> tuple[str, dict]:
    course = client.post("/api/demo/sample", headers={"X-Demo-User": owner}).json()
    return course["id"], {"X-Demo-User": owner}


def wait(cid: str, rid: str, h: dict) -> dict:
    for _ in range(200):
        r = client.get(f"/api/courses/{cid}/revisions/{rid}", headers=h).json()
        if r["status"] not in ("queued", "running"):
            return r
        import time
        time.sleep(0.02)
    raise AssertionError("revision did not finish")


def names(cid: str, h: dict) -> dict:
    return {c["name"]: c for c in client.get(f"/api/courses/{cid}", headers=h).json()["concepts"]}


def test_a_request_with_files_is_proposed_checked_and_applied_only_when_chosen():
    cid, h = owner_course("owner-r1")
    student = {"X-Demo-User": "stu-r1"}
    client.put(f"/api/courses/{cid}/me", json={"weekly_minutes": 180}, headers=student)
    chain = names(cid, h)["Derivatives and the Chain Rule"]
    step = client.post(f"/api/courses/{cid}/check/next", json={"session": []}, headers=student).json()
    client.post(f"/api/courses/{cid}/answer", json={"question_id": step["question"]["id"], "choice": 0}, headers=student)

    r = client.post(f"/api/courses/{cid}/revisions", headers=h,
                    data={"prompt": "Logarithms aren't needed in this course. Add what the study guide says week 11 relies on."},
                    files=[("files", ("study_guide.txt", STUDY_GUIDE, "text/plain")), ("files", ("midterm.txt", SAMPLE_EXAM, "text/plain"))])
    assert r.status_code == 200, r.text
    rev = wait(cid, r.json()["id"], h)
    assert rev["status"] == "ready", rev
    assert [f["filename"] for f in rev["files"]] == ["study_guide.txt", "midterm.txt"]
    by_kind = {}
    for ch in rev["changes"]:
        by_kind.setdefault(ch["kind"], []).append(ch)

    removal = by_kind["remove_concept"][0]
    assert removal["name"] == "Logarithms and Exponentials" and removal["selected"] and not removal["source"]
    added = by_kind["add_concept"][0]
    assert added["name"] == "Integration and Area Under a Curve"
    assert added["needs"][0]["week"] == 11 and added["quote_ok"] and added["source"].startswith("study_guide.txt")
    assert added["questions"], "a new concept gets its own study questions"
    question = by_kind["add_question"][0]
    assert question["name"] == "Derivatives and the Chain Rule" and question["quote_ok"]
    assert question["questions"][0]["choices"][question["questions"][0]["correct_index"]] == "2x cos(x^2)"
    assert "prof@school.example" not in str(api.services.course(cid).revisions.get(rev["id"]).files), "files are redacted"

    # Nothing changed yet.
    before = names(cid, h)
    assert "Logarithms and Exponentials" in before and "Integration and Area Under a Curve" not in before

    # Apply all but the removal.
    keep = [ch["id"] for ch in rev["changes"] if ch["kind"] != "remove_concept"]
    done = client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", json={"change_ids": keep}, headers=h).json()
    assert done["applied"] == len(keep) and done["revision"]["status"] == "applied"
    after = names(cid, h)
    assert "Integration and Area Under a Curve" in after and "Logarithms and Exponentials" in after
    assert after["Integration and Area Under a Curve"]["next_need"]["week"] == 11
    repo = api.services.course(cid)
    copied = [q for q in repo.questions.list() if q.origin == "instructor"]
    assert len(copied) == 1 and copied[0].concept_id == chain["id"]
    assert repo.responses.list(student="stu-r1"), "students' answers survive a revision"
    trace = client.get(f"/api/courses/{cid}/review", headers=h).json()["trace"]
    assert trace[-1]["stage"] == "Revised by the course owner" and any("study_guide.txt" in n for n in trace[-1]["notes"])
    assert client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", json={"change_ids": keep}, headers=h).status_code == 409


def test_only_the_owner_can_ask_see_or_apply():
    cid, h = owner_course("owner-r2")
    other = {"X-Demo-User": "stu-r2"}
    assert client.post(f"/api/courses/{cid}/revisions", headers=other, data={"prompt": "Remove logarithms please"}).status_code == 403
    rev = client.post(f"/api/courses/{cid}/revisions", headers=h, data={"prompt": "Logarithms are not needed."}).json()
    assert client.get(f"/api/courses/{cid}/revisions", headers=other).status_code == 403
    assert client.get(f"/api/courses/{cid}/revisions/{rev['id']}", headers=other).status_code == 403
    rev = wait(cid, rev["id"], h)
    assert client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", headers=other,
                       json={"change_ids": [rev["changes"][0]["id"]]}).status_code == 403
    assert client.post(f"/api/courses/{cid}/revisions", headers=h, data={"prompt": "x"}).status_code == 400, "say something or add a file"
    assert client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", headers=h, json={"change_ids": ["chg_bogus"]}).status_code == 400
    removed = client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", headers=h, json={"change_ids": [rev["changes"][0]["id"]]}).json()
    assert removed["applied"] == 1 and "Logarithms and Exponentials" not in names(cid, h)
    assert [r["id"] for r in client.get(f"/api/courses/{cid}/revisions", headers=h).json()] == [rev["id"]]


def test_discarding_changes_nothing():
    cid, h = owner_course("owner-r3")
    rev = wait(cid, client.post(f"/api/courses/{cid}/revisions", headers=h, data={"prompt": "Logarithms are not needed."}).json()["id"], h)
    assert client.post(f"/api/courses/{cid}/revisions/{rev['id']}/discard", headers=h).json()["status"] == "discarded"
    assert "Logarithms and Exponentials" in names(cid, h)
    assert client.post(f"/api/courses/{cid}/revisions/{rev['id']}/apply", headers=h,
                       json={"change_ids": [rev["changes"][0]["id"]]}).status_code == 409


class Scripted(OfflineEngine):
    """Returns a fixed plan, including mistakes code must catch."""

    def __init__(self, plan_for):
        self.plan_for = plan_for

    def revise_map(self, ctx):
        return self.plan_for(ctx)


def run_plan(ctx, plan_for, prompt="fix it", files=()):
    course = sample.create_sample(ctx, "owner")
    ctx.engine = Scripted(plan_for)
    repo = ctx.course(course.id)
    rev = Revision(owner="owner", prompt=prompt, files=[revise.read_file(ctx.engine, f"f{i}", name, data, "text/plain")
                                                       for i, (name, data) in enumerate(files, start=1)])
    repo.revisions.put(rev)
    revise.propose(ctx, course.id, rev.id)
    return course, repo, repo.revisions.get(rev.id)


def test_code_drops_or_flags_what_the_model_gets_wrong(ctx):
    def plan_for(rc):
        week = {it.week: it.id for it in rc.items}
        cid = {c.name: c.id for c in rc.concepts}
        return RevisionPlan(summary="s", changes=[
            MapChange(action="remove", concept_id="cpt_does_not_exist", reason="invented id"),
            MapChange(action="add", name="Simple Linear Regression", add_needs=[NeedRef(item_id=week[11])], reason="already on the map"),
            MapChange(action="add", name="Hypothesis Testing", summary="p-values", add_needs=[NeedRef(item_id="tpc_bogus")], reason="no real week"),
            MapChange(action="add", name="Bayes' Rule", summary="Updating probabilities.", add_needs=[NeedRef(item_id=week[7])],
                      builds_on=[cid["Basic Probability"], "cpt_bogus"], reason="the guide says so", source="f1.1", quote="something not in the file"),
            MapChange(action="edit", concept_id=cid["Python Fundamentals"], reason="no actual change"),
            MapChange(action="needs", concept_id=cid["Python Fundamentals"], remove_needs=[week[13], "tpc_bogus"], reason="not used"),
        ], questions=[
            SourceQuestion(concept=cid["Basic Probability"], prompt="Pick one", choices=["a", "a", "b", "c"], correct_index=0),
            SourceQuestion(concept="Bayes' Rule", prompt="What is P(A|B)?", choices=["P(B|A)P(A)/P(B)", "P(A)P(B)", "P(A)+P(B)", "1"],
                           correct_index=0, source="f1.1"),
        ])

    course, repo, rev = run_plan(ctx, plan_for, files=[("guide.txt", b"Week 7: Naive Bayes uses Bayes' rule.\n")])
    kinds = [(ch.kind, ch.name) for ch in rev.changes]
    assert ("remove_concept", "") not in kinds and not any(ch.concept_id == "cpt_does_not_exist" for ch in rev.changes)
    assert ("add_concept", "Simple Linear Regression") not in kinds, "an existing concept is attached to weeks, not added twice"
    assert ("add_need", "Simple Linear Regression") in kinds
    assert ("add_concept", "Hypothesis Testing") not in kinds and any("Hypothesis Testing" in n for n in rev.not_done)
    bayes = next(ch for ch in rev.changes if ch.kind == "add_concept")
    assert bayes.name == "Bayes' Rule" and not bayes.quote_ok and not bayes.selected and "isn't in that file" in bayes.note
    assert len(bayes.builds_on) == 1, "only real concept ids"
    assert not any(ch.kind == "edit_concept" for ch in rev.changes)
    python_weeks = [ch for ch in rev.changes if ch.kind == "remove_need"]
    assert len(python_weeks) <= 1, "only weeks that really use it can be removed"
    questions = [ch for ch in rev.changes if ch.kind == "add_question"]
    assert len(questions) == 1 and questions[0].name == "Bayes' Rule" and not questions[0].quote_ok and not questions[0].selected

    # Applying the new concept links it to what it builds on, without cycles, and its question follows it.
    result = revise.apply(ctx, course.id, rev, [bayes.id, questions[0].id])
    assert result["applied"] == 2
    new = next(c for c in repo.concepts.list() if c.name == "Bayes' Rule")
    assert any(e.dst == new.id for e in repo.edges.list())
    assert any(q.concept_id == new.id and q.origin == "instructor" for q in repo.questions.list())
    snap = Snapshot.load(course, repo, "s", ctx.now().date())
    assert new.id in snap.concepts and plan(snap)["weeks"] is not None


def test_a_removed_concept_can_be_brought_back(ctx):
    course = sample.create_sample(ctx, "owner")
    repo = ctx.course(course.id)
    logs = next(c for c in repo.concepts.list() if c.name == "Logarithms and Exponentials")
    logs.removed = True
    repo.concepts.put(logs)
    week6 = next(t for t in repo.topics.list() if t.week == 6)
    ctx.engine = Scripted(lambda rc: RevisionPlan(summary="s", changes=[
        MapChange(action="add", name="Logarithms and Exponentials", add_needs=[NeedRef(item_id=week6.id)], reason="needed after all")]))
    rev = Revision(owner="owner", prompt="Bring logarithms back for week 6")
    repo.revisions.put(rev)
    revise.propose(ctx, course.id, rev.id)
    rev = repo.revisions.get(rev.id)
    back = rev.changes[0]
    assert back.kind == "add_concept" and back.concept_id == logs.id and back.concept.refresher == logs.refresher
    revise.apply(ctx, course.id, rev, [back.id])
    assert not repo.concepts.get(logs.id).removed


def test_a_failed_model_call_is_reported_not_hidden(ctx):
    def boom(rc):
        raise RuntimeError("model unavailable")

    _, _, rev = run_plan(ctx, boom)
    assert rev.status == "error" and rev.error


def test_weeks_named_by_number_are_placed_and_numbering_is_dropped(ctx):
    def plan_for(rc):
        return RevisionPlan(summary="s", changes=[
            MapChange(action="add", name="Bayes' Rule", summary="Updating probabilities.", add_needs=[NeedRef(item_id="Week 7")], reason="r"),
            MapChange(action="add", name="Hypothesis Testing", add_needs=[NeedRef(item_id="week 40")], reason="r"),
        ], questions=[SourceQuestion(concept="Bayes' Rule", prompt="1. What is P(A|B)?", choices=["A) P(B|A)P(A)/P(B)", "B) P(A)P(B)", "C) P(A)+P(B)", "D) 1"],
                                     correct_index=0, key_from_file=True, source="f1.1")])

    _, repo, rev = run_plan(ctx, plan_for, files=[("quiz.txt", b"1. What is P(A|B)?\nA) P(B|A)P(A)/P(B)\nB) P(A)P(B)\nC) P(A)+P(B)\nD) 1\n")])
    bayes = next(ch for ch in rev.changes if ch.kind == "add_concept")
    week7 = next(t for t in repo.topics.list() if t.week == 7)
    assert [r.topic_id for r in bayes.needs] == [week7.id]
    assert any("Hypothesis Testing" in n and "week 40" in n for n in rev.not_done)
    q = next(ch for ch in rev.changes if ch.kind == "add_question")
    assert q.questions[0].prompt == "What is P(A|B)?" and q.quote_ok and q.selected
    assert q.questions[0].choices[0] == "P(B|A)P(A)/P(B)", "the file's option letters are dropped"

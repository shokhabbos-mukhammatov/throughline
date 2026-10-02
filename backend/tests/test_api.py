import os
import tempfile
import time

os.environ["THROUGHLINE_OFFLINE"] = "1"
os.environ["PERSIST"] = "0"
os.environ["BULLETIN_LIVE"] = "0"
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())

from fastapi.testclient import TestClient  # noqa: E402

from throughline.api import app  # noqa: E402
from throughline.seed import sample  # noqa: E402

client = TestClient(app)
OWNER = {"X-Demo-User": "owner-1"}
STUDENT = {"X-Demo-User": "student-1"}


def test_requires_identity():
    assert client.get("/api/courses/mine").status_code == 401


def test_sample_course_student_flow_and_class_view():
    course = client.post("/api/demo/sample", headers=OWNER).json()
    cid = course["id"]

    joined = client.get(f"/api/join/{course['join_code']}").json()
    assert joined["id"] == cid and "syllabus_text" not in joined

    detail = client.get(f"/api/courses/{cid}", headers=STUDENT).json()
    assert detail["week_now"] == 4 and not detail["is_owner"] and not detail["enrolled"]
    assert any(c["hidden"] for c in detail["concepts"]) and detail["ai_policy"]["stance"] == "limited"

    chain = next(c for c in detail["concepts"] if c["name"] == "Derivatives and the Chain Rule")
    me = client.put(f"/api/courses/{cid}/me", json={"route": "equivalent", "weekly_minutes": 120,
                                                       "self_report": {chain["id"]: "never", "bogus": "never"}}, headers=STUDENT).json()
    assert me["route"] == "equivalent" and me["self_report"] == {chain["id"]: "never"}

    step = client.post(f"/api/courses/{cid}/check/next", json={"session": []}, headers=STUDENT).json()
    assert not step["done"] and step["reason"] and "correct_index" not in step["question"], "the answer key must never reach the client"
    assert step["question"]["concept_id"] != chain["id"], "never-studied concepts go to Learn, not to a quiz"
    result = client.post(f"/api/courses/{cid}/answer", json={"question_id": step["question"]["id"], "choice": 0}, headers=STUDENT).json()
    assert result["status_after"] in ("likely", "refresh", "learn") and "explanation" in result and result["response_id"]
    step2 = client.post(f"/api/courses/{cid}/check/next", json={"session": [result["response_id"]]}, headers=STUDENT).json()
    assert step2["done"] or step2["question"]["id"] != step["question"]["id"]

    graph = client.get(f"/api/courses/{cid}/graph", headers=STUDENT).json()
    names = {n["id"]: n["name"] for n in graph["nodes"]}
    assert ("Simple Linear Regression", "Multiple Linear Regression") in {(names[e["src"]], names[e["dst"]]) for e in graph["edges"]}
    assert graph["needs"] and "DEMO 212" in graph["prereqs"]

    plan = client.get(f"/api/courses/{cid}/plan", headers=STUDENT).json()
    assert plan["weekly_minutes"] == 120 and plan["counts"]["learn"] >= 1

    study = client.get(f"/api/courses/{cid}/concepts/{chain['id']}", headers=STUDENT).json()
    assert study["status"] == "learn" and study["learn_outline"] and study["resources"][0]["url"].startswith("https://")
    assert study["coverage"] == "missing" and study["evidence_items"][0]["source"] == "This syllabus"
    assert study["practice"] and "correct_index" not in study["practice"]

    # Class view is owner-only and aggregate-only.
    assert client.get(f"/api/courses/{cid}/class", headers=STUDENT).status_code == 403
    view = client.get(f"/api/courses/{cid}/class", headers=OWNER).json()
    assert view["simulated"] == 26 and view["students"] == 27
    rows = {r["name"]: r for r in view["rows"]}
    assert not rows["Derivatives and the Chain Rule"]["suppressed"]
    assert rows["Version Control with Git"]["suppressed"] and rows["Version Control with Git"]["first_try"] is None
    assert view["concerns"]
    real_only = client.get(f"/api/courses/{cid}/class?include_simulated=false", headers=OWNER).json()
    assert real_only["students"] == 1 and all(r["suppressed"] for r in real_only["rows"])

    review = client.get(f"/api/courses/{cid}/review", headers=OWNER).json()
    assert review["edges"] and any(t["stage"] == "Checking what prerequisites taught" for t in review["trace"])

    gone = client.delete(f"/api/courses/{cid}/me", headers=STUDENT).json()
    assert gone["deleted_responses"] >= 1
    assert client.get(f"/api/courses/{cid}/class?include_simulated=false", headers=OWNER).json()["students"] == 0


def test_add_course_from_pasted_syllabus_and_review():
    start = sample.term_start(time.localtime() and __import__("datetime").date.today())
    text = sample.syllabus_text(start).replace("DEMO 410", "TEST 410")
    course = client.post("/api/courses", data={"code": "test410", "text": text}, headers=OWNER).json()
    assert course["code"] == "TEST 410"
    for _ in range(100):
        state = client.get(f"/api/courses/{course['id']}", headers=OWNER).json()
        if state["build"]["status"] in ("ready", "error"):
            break
        time.sleep(0.05)
    assert state["build"]["status"] == "ready", state["build"]
    assert state["is_owner"] and state["timeline"]

    review = client.get(f"/api/courses/{course['id']}/review", headers=OWNER).json()
    q = review["concepts"][0]["questions"][0]
    patched = client.patch(f"/api/courses/{course['id']}/questions/{q['id']}", json={"status": "rejected"}, headers=OWNER).json()
    assert patched["status"] == "rejected"
    assert client.get(f"/api/courses/{course['id']}/review", headers=STUDENT).status_code == 403


def test_rejects_old_doc_and_empty_input():
    resp = client.post("/api/courses", data={"code": "X 1"}, files={"file": ("s.doc", b"\xd0\xcf\x11\xe0" * 40, "application/msword")}, headers=OWNER)
    assert resp.status_code == 415 and "PDF" in resp.json()["detail"]
    assert client.post("/api/courses", data={"code": "X 1", "text": "  "}, headers=OWNER).status_code == 400


def test_bulletin_snapshot_endpoint():
    entry = client.get("/api/bulletin/ds612").json()
    assert entry["code"] == "DS 612" and "DS 212" in entry["prereq_codes"]
    assert client.get("/api/bulletin/ZZZ 999").status_code == 404


def test_prerequisite_syllabus_upload_rechecks_coverage():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-2"}).json()
    files = {"file": ("demo212.txt", b"Week 3: Gradients, derivatives and the chain rule for scientists\nWeek 4: more", "text/plain")}
    resp = client.post(f"/api/courses/{course['id']}/prereq-syllabus", data={"prereq_code": "DEMO 212"}, files=files, headers={"X-Demo-User": "owner-2"})
    assert resp.status_code == 200
    for _ in range(100):
        detail = client.get(f"/api/courses/{course['id']}", headers={"X-Demo-User": "owner-2"}).json()
        rechecked = any(t["stage"] == "Re-checking what prerequisites taught" for t in detail["build"]["trace"])
        if rechecked and detail["build"]["status"] == "ready":  # the stage shows up when it starts, not when it ends
            break
        time.sleep(0.05)
    chain = next(c for c in detail["concepts"] if c["name"] == "Derivatives and the Chain Rule")
    assert chain["coverage"] == "missing", "the instructor's 'no calculus required' note still wins"
    assert client.post(f"/api/courses/{course['id']}/prereq-syllabus", data={"prereq_code": "X"}, files=files, headers=STUDENT).status_code == 403

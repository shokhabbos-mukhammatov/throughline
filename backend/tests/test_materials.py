"""A student's own notes and slides from a prerequisite course."""

import io
import zipfile

from fastapi.testclient import TestClient

from throughline import api
from throughline.materials import build_material, pptx_sections, read_material
from throughline.seed import sample

client = TestClient(api.app)


def pptx(slides: list[str], notes: dict[int, str] | None = None) -> bytes:
    """A minimal .pptx: just the parts the reader uses."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, text in enumerate(slides, start=1):
            body = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in text.split("\n"))
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:a="a" xmlns:p="p"><p:txBody>{body}</p:txBody></p:sld>')
        for i, text in (notes or {}).items():
            z.writestr(f"ppt/notesSlides/notesSlide{i}.xml", f'<p:notes xmlns:a="a" xmlns:p="p"><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:notes>')
    return buf.getvalue()


SLIDES = pptx(
    ["MATH 108 Week 3\nLines and slopes", "The chain rule\nd/dx f(g(x)) = f'(g(x)) g'(x)", "Logarithms\nlog(ab) = log a + log b",
     "Office hours: email prof.smith@sfsu.edu"],
    notes={2: "Practice: differentiate sin(x^2) using the chain rule"},
)


def test_slides_are_read_one_section_per_slide_with_speaker_notes(ctx):
    sections = pptx_sections(SLIDES)
    assert [loc for loc, _ in sections] == ["slide 1", "slide 2", "slide 3", "slide 4"]
    assert "sin(x^2)" in sections[1][1], "speaker notes belong to their slide"
    kind, _ = read_material(ctx.engine, SLIDES, "week3.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
    assert kind == "slides"


def test_materials_match_concepts_with_locations_and_redact_contacts(ctx):
    course = sample.create_sample(ctx, "owner")
    concepts = [c for c in ctx.course(course.id).concepts.list() if not c.removed]
    m = build_material(ctx.engine, concepts, "stu", "MATH 108", "week3.pptx", SLIDES, "application/octet-stream")
    by_name = {c.id: c.name for c in concepts}
    found = {by_name[x.concept_id]: x.loc for x in m.matches}
    assert found.get("Derivatives and the Chain Rule") == "slide 2"
    assert found.get("Logarithms and Exponentials") == "slide 3"
    assert all("prof.smith@sfsu.edu" not in ch.text for ch in m.chunks), "emails are redacted before storage"


def test_upload_is_private_feeds_the_plan_and_is_deleted_with_my_data():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-m"}).json()
    cid = course["id"]
    me, other = {"X-Demo-User": "stu-m1"}, {"X-Demo-User": "stu-m2"}
    r = client.post(f"/api/courses/{cid}/materials", headers=me, data={"prereq_code": "math 108"},
                    files={"file": ("week3.pptx", SLIDES, "application/octet-stream")})
    assert r.status_code == 200, r.text
    mat = r.json()
    assert mat["prereq_code"] == "MATH 108" and mat["kind"] == "slides"
    assert any(c["name"] == "Derivatives and the Chain Rule" and c["locs"] == ["slide 2"] for c in mat["covers"])

    assert client.get(f"/api/courses/{cid}/materials", headers=other).json() == [], "other students never see it"
    assert client.delete(f"/api/courses/{cid}/materials/{mat['id']}", headers=other).status_code == 404

    detail = client.get(f"/api/courses/{cid}", headers=me).json()
    chain = next(c for c in detail["concepts"] if c["name"] == "Derivatives and the Chain Rule")
    assert chain["in_your_notes"][0]["loc"] == "slide 2"
    client.put(f"/api/courses/{cid}/me", json={"self_report": {chain["id"]: "never"}, "weekly_minutes": 600}, headers=me)
    p = client.get(f"/api/courses/{cid}/plan", headers=me).json()
    items = [i for w in p["weeks"] for i in w["items"]] + p["at_risk"]
    study = next(i for i in items if i["name"] == "Derivatives and the Chain Rule")["study"]
    assert study[0]["kind"] == "notes" and study[0]["detail"] == "slide 2" and "MATH 108 slides" in study[0]["title"]
    assert any(s["url"] for s in study[1:]), "a free textbook section follows the student's own notes"

    gone = client.delete(f"/api/courses/{cid}/me", headers=me).json()
    assert gone["deleted_materials"] == 1
    assert client.get(f"/api/courses/{cid}/materials", headers=me).json() == []


def test_unreadable_files_are_refused_clearly():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-m3"}).json()
    r = client.post(f"/api/courses/{course['id']}/materials", headers={"X-Demo-User": "stu-m3"},
                    files={"file": ("old.ppt", b"binary", "application/vnd.ms-powerpoint")})
    assert r.status_code == 415 and ".pptx" in r.json()["detail"]


def test_prereq_choice_must_be_a_listed_alternative():
    course = client.post("/api/demo/sample", headers={"X-Demo-User": "owner-m4"}).json()
    url, h = f"/api/courses/{course['id']}/me", {"X-Demo-User": "stu-m4"}
    assert client.put(url, json={"prereq_taken": "demo 212"}, headers=h).json()["prereq_taken"] == "DEMO 212"
    assert client.put(url, json={"prereq_taken": "CHEM 101"}, headers=h).status_code == 422
    assert client.put(url, json={"prereq_taken": ""}, headers=h).json()["prereq_taken"] is None

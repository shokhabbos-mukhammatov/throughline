"""Exercise the Gemini code paths against the real SDK types, with simulated responses (no network)."""

import json

import pytest
from google.genai import _transformers, types

from throughline.config import Settings
from throughline.ctx import Ctx
from throughline.llm import schemas
from throughline.llm.gemini import GeminiEngine
from throughline.mapping import build_course
from throughline.models import Course
from throughline.store.memory import MemoryStore


@pytest.fixture
def gemini():
    return GeminiEngine(Settings(gemini_api_key="test-key", offline=False))


@pytest.mark.parametrize("schema", [schemas.SyllabusParse, schemas.MappingResult, schemas.ConceptPacks, schemas.Solutions,
                                    schemas.SameConceptJudgments, schemas.CoverageJudgments])
def test_response_schemas_convert(gemini, schema):
    assert _transformers.t_schema(gemini.client, schema) is not None
    cfg = gemini.config(schema=schema, system="x")
    assert cfg.response_mime_type == "application/json"
    assert cfg.thinking_config.thinking_level == types.ThinkingLevel.LOW


def _response(text: str):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]))])


def test_structured_strips_code_fences(gemini, monkeypatch):
    payload = {"solutions": [{"question_id": "q1", "choice": 2, "note": ""}]}
    monkeypatch.setattr(gemini.client.models, "generate_content", lambda **kw: _response("```json\n" + json.dumps(payload) + "\n```"))
    assert gemini._structured("x", schemas.Solutions, "sys").solutions[0].choice == 2


def test_full_build_with_simulated_gemini(gemini, monkeypatch, tmp_path):
    """Drive build_course through the Gemini engine with canned JSON, checking validation and verification."""
    def fake(model, contents, config):
        system = config.system_instruction or ""
        if "structured timeline" in system:
            return _response(json.dumps({
                "code": "DS 612", "title": "Data Mining", "term": "Fall 2026", "term_start": "2026-08-25",
                "official_prereqs": ["DS 212"], "prereq_text": "DS 212 or equivalent", "prereq_routes": ["or equivalent"],
                "ai_stance": "limited", "ai_summary": "AI allowed for code, not prose.", "timeline_kind": "assessments",
                "timeline": [{"week": 4, "date": "2026-09-15", "title": "Quiz 1", "details": "simple linear regression", "kind": "assessment"}],
                "taught_here": ["Python"], "free_resources": [{"title": "ISLP", "url": "https://www.statlearning.com"}],
            }))
        if "EARLIER" in system:
            seen["perspectives"].add(system.split("Perspective for this pass:")[1].split("\n")[0])
            item_id = contents.split("item_id=")[1].split(" ")[0]
            run = len(seen["perspectives"])
            regression = "Simple Linear Regression" if run != 2 else "Least Squares Regression"  # one run names it differently
            return _response(json.dumps({"items": [
                {"item_id": item_id, "requires": [
                    {"name": regression, "summary": "Fitting a line.", "importance": "essential", "how_used": "Quiz 1 covers it.",
                     "depth": "interpret slope", "covered_by": "DS 212", "evidence": "DS 212 lists regression analysis.",
                     "builds_on": [{"name": "Descriptive Statistics", "summary": "Means and spreads."}]},
                    {"name": "Matrix Algebra", "summary": "s", "importance": "helpful", "how_used": "x", "depth": "d",
                     "covered_by": "MATH 999", "evidence": ""}]},
                {"item_id": "invented", "requires": [{"name": "Ghost", "summary": "", "importance": "essential", "how_used": "", "depth": ""}]},
            ]}))
        if "SAME concept" in system:
            ids = [line.split("pair_id=")[1] for line in contents.splitlines() if line.startswith("pair_id=")]
            seen["judged"] += len(ids)
            return _response(json.dumps({"judgments": [{"pair_id": i, "same": "Least Squares" in contents, "reason": "r"} for i in ids]}))
        if "actually teaches" in system:
            ids = [line.split("concept_id=")[1].split(" ")[0] for line in contents.splitlines() if line.startswith("concept_id=")]
            out = []
            for block, cid in zip(contents.split("concept_id=")[1:], ids):
                if "Regression" in block.split("\n")[0]:
                    label = block.split("[")[1].split("]")[0]
                    out.append({"concept_id": cid, "verdict": "teaches", "passage": label, "quote": "regression analysis"})
                else:
                    out.append({"concept_id": cid, "verdict": "unrelated", "passage": None, "quote": ""})
            return _response(json.dumps({"judgments": out}))
        if "study material" in system:
            ids = [line.split("concept_id=")[1].split(" ")[0] for line in contents.splitlines() if line.startswith("concept_id=")]
            q = lambda i: {"prompt": f"Q{i}", "choices": ["right", "w1", "w2", "w3"], "correct_index": 0, "explanation": "e"}
            return _response(json.dumps({"packs": [
                {"concept_id": cid, "refresher": "r", "learn_outline": "l", "refresh_minutes": 15, "learn_minutes": 200,
                 "resource_ids": ["syl1", "os-stats-reg", "made-up"], "questions": [q(1), q(2), q(3), q(4)]} for cid in ids]}))
        if "independently" in system:
            blocks = contents.split("question_id=")[1:]
            sols = []
            for n, b in enumerate(blocks):
                qid = b.split("\n")[0]
                right = [line for line in b.splitlines() if line.strip().endswith("right")][0].strip().split(".")[0]
                sols.append({"question_id": qid, "choice": int(right) if n else (int(right) + 1) % 4, "note": ""})
            return _response(json.dumps({"solutions": sols}))
        raise AssertionError(system[:60])

    seen = {"perspectives": set(), "judged": 0}

    def fake_embed(model, contents, config):
        # Regression spellings land close together (ambiguous band), everything else far apart.
        def vec(text):
            if "Least Squares" in text:
                return [0.6, 1.0] + [0.0] * 766  # cosine 0.88 with the next one: the judge decides
            if "Regression" in text:
                return [1.0, 0.6] + [0.0] * 766
            return [0.0] * (len(text) % 700) + [1.0] + [0.0] * (767 - len(text) % 700)
        return types.EmbedContentResponse(embeddings=[types.ContentEmbedding(values=vec(t)) for t in contents])

    monkeypatch.setattr(gemini.client.models, "generate_content", fake)
    monkeypatch.setattr(gemini.embed_client.models, "embed_content", fake_embed)
    ctx = Ctx(store=MemoryStore(), engine=gemini, settings=Settings(offline=False, bulletin_live=False, gemini_api_key="k"))
    course = Course(owner="me", code="DS 612", syllabus_text="syllabus " * 20)
    monkeypatch.setitem(__import__("throughline.bulletin", fromlist=["SNAPSHOT"]).SNAPSHOT, "DS 212", __import__("throughline.bulletin", fromlist=["SNAPSHOT"]).SNAPSHOT["DS 212"])
    ctx.catalog.put(course)
    build_course(ctx, course.id, "DS 612")
    course = ctx.catalog.get(course.id)
    repo = ctx.course(course.id)
    assert course.build.status == "ready", course.build.error
    assert course.timeline_kind == "assessments" and course.resources[0].kind == "syllabus"
    topic = repo.topics.list()[0]
    assert topic.week == 4 and topic.kind == "assessment"
    concepts = {c.name: c for c in repo.concepts.list()}
    assert "Ghost" not in concepts, "requirements for invented item ids are dropped"
    assert len(seen["perspectives"]) == 3, "three independent mapping runs, each from a different angle"
    reg = concepts["Simple Linear Regression"]
    assert "Least Squares Regression" in reg.aliases and seen["judged"] >= 1, "names merged via the same-concept judge"
    assert reg.confidence == 1.0 and concepts["Descriptive Statistics"].foundation
    assert reg.coverage == "listed" and reg.covered_by == "DS 212" and "regression analysis" in reg.evidence
    assert concepts["Matrix Algebra"].coverage == "unknown", "coverage by a course that isn't a listed prerequisite doesn't count"
    assert [r.title for r in reg.resources] == ["ISLP", "Introductory Statistics (OpenStax)"], "unknown resource ids are dropped"
    edges = repo.edges.list()
    assert len(edges) == 1 and edges[0].src == concepts["Descriptive Statistics"].id
    trace = {t.stage: t.calls for t in course.build.trace}
    assert trace["Mapping prerequisites"]["map_prerequisites"] == 3
    assert trace["Checking what prerequisites taught"].get("judge_coverage") == 1
    qs = repo.questions.list()
    assert len(qs) == 9, "at most 3 questions per concept"
    assert all(q.choices[q.correct_index] == "right" for q in qs), "shuffling keeps the key aligned"
    flagged = [q for q in qs if q.verification == "disagreed"]
    assert flagged and all(q.status == "draft" for q in flagged)
    assert all(q.status == "approved" for q in qs if q.verification == "agreed")

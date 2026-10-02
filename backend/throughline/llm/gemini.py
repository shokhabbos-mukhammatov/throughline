"""Gemini implementation of the engine (google-genai SDK; AI Studio key or Vertex AI)."""

from __future__ import annotations

import json
import logging
from typing import TypeVar

import numpy as np

from google import genai
from google.genai import types
from pydantic import BaseModel

from ..config import Settings
from ..seed import library
from . import prompts
from .base import ConceptCard, CourseContext, CoverageRequest, ItemCard, PairCard, QuestionCard, ResourceCard
from .schemas import ConceptPacks, CoverageJudgments, MappingResult, SameConceptJudgments, Solutions, SyllabusParse

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
_EMBED_BATCH = 100


def _context_block(ctx: CourseContext) -> str:
    parts = []
    if ctx.prereq_text:
        parts.append(f"Prerequisite statement: {ctx.prereq_text}")
    if ctx.official_prereqs:
        parts.append("Listed prerequisite courses: " + ", ".join(ctx.official_prereqs))
    if ctx.bulletin:
        parts.append("Bulletin descriptions:\n" + "\n".join(f"- {b}" for b in ctx.bulletin))
    if ctx.informal_requirements:
        parts.append("Informal requirements: " + " | ".join(ctx.informal_requirements))
    if ctx.instructor_notes:
        parts.append("Instructor notes: " + " | ".join(ctx.instructor_notes))
    if ctx.taught_here:
        parts.append("Taught in this course: " + "; ".join(ctx.taught_here))
    return "\n".join(parts) or "(none)"


class GeminiEngine:
    online = True

    def __init__(self, settings: Settings):
        self.s = settings
        http = types.HttpOptions(
            retry_options=types.HttpRetryOptions(
                attempts=4, initial_delay=1.0, max_delay=20.0, http_status_codes=[408, 429, 500, 502, 503, 504]
            )
        )
        if settings.use_vertex:
            self.client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location, http_options=http)
            self.embed_client = genai.Client(vertexai=True, project=settings.gcp_project, location=settings.embed_location, http_options=http)
            self.label = f"{settings.model} · Vertex AI"
        else:
            self.client = genai.Client(api_key=settings.gemini_api_key, http_options=http)
            self.embed_client = self.client
            self.label = f"{settings.model} · Gemini API"
    def config(self, *, schema: type[BaseModel] | None = None, system: str | None = None, thinking: str | None = None) -> types.GenerateContentConfig:
        kwargs: dict = {"system_instruction": system}
        if schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = schema
        if self.s.model.startswith("gemini-3"):
            # Gemini 3 is tuned for the default temperature; thinking level trades depth for latency.
            level = thinking or self.s.thinking_level
            if level:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level=level.upper())
        else:
            kwargs["temperature"] = 0.2
        return types.GenerateContentConfig(**kwargs)

    def _structured(self, contents, schema: type[T], system: str, thinking: str | None = None) -> T:
        resp = self.client.models.generate_content(model=self.s.model, contents=contents,
                                                   config=self.config(schema=schema, system=system, thinking=thinking))
        if isinstance(resp.parsed, schema):
            return resp.parsed
        text = resp.text or ""
        try:
            return schema.model_validate_json(text)
        except Exception:
            # Occasionally the JSON arrives wrapped in a code fence.
            cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
            return schema.model_validate(json.loads(cleaned))
    def read_document(self, data: bytes, mime: str, filename: str) -> str:
        resp = self.client.models.generate_content(
            model=self.s.model,
            contents=[types.Part.from_bytes(data=data, mime_type=mime), f"File name: {filename}"],
            config=self.config(system=prompts.READ_DOCUMENT),
        )
        return resp.text or ""

    def ping(self) -> None:
        """One tiny call that proves the credentials and model work (raises on failure)."""
        self.client.models.generate_content(model=self.s.model, contents="Reply with the single word ok.",
                                            config=self.config(thinking="low"))

    def parse_syllabus(self, text: str, hint_code: str) -> SyllabusParse:
        contents = f"Course code entered by the student: {hint_code or '(none)'}\n\nSyllabus:\n\n{text[:120_000]}"
        return self._structured(contents, SyllabusParse, prompts.PARSE_SYLLABUS)

    def map_prerequisites(self, ctx: CourseContext, items: list[ItemCard], known: list[str], sample: int = 0) -> MappingResult:
        lines = []
        for it in items:
            when = f" ({it.date})" if it.date else ""
            kind = "Assessment" if it.kind == "assessment" else "Lecture"
            lines.append(f"- item_id={it.id} | Week {it.week}{when} | {kind}: {it.title}" + (f" — {it.details}" if it.details else ""))
        contents = (
            "Timeline items:\n" + "\n".join(lines)
            + "\n\nStandard concept names (use one when it is the same idea):\n" + "\n".join(f"- {c.name}" for c in library.CONCEPTS)
            + "\n\nConcepts already identified:\n" + ("\n".join(f"- {k}" for k in known) or "(none yet)")
        )
        perspective = prompts.PERSPECTIVES[sample % len(prompts.PERSPECTIVES)]
        system = prompts.MAP_PREREQUISITES.format(course=ctx.label, context=_context_block(ctx), perspective=perspective)
        # Mapping is the judgment everything else rests on, so it gets more reasoning than the other calls.
        return self._structured(contents, MappingResult, system, thinking=self.s.map_thinking_level)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = [t[:8000] for t in texts[start : start + _EMBED_BATCH]]
            resp = self.embed_client.models.embed_content(
                model=self.s.embed_model,
                contents=batch,
                config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=self.s.embed_dim),
            )
            for emb in resp.embeddings or []:
                vec = np.asarray(emb.values, dtype=np.float32)
                norm = float(np.linalg.norm(vec)) or 1.0  # truncated dimensions must be re-normalized
                out.append((vec / norm).tolist())
        if len(out) != len(texts):
            raise RuntimeError(f"embedding returned {len(out)} vectors for {len(texts)} texts")
        return out

    def judge_same(self, pairs: list[PairCard]) -> SameConceptJudgments:
        lines = [f"pair_id={p.pair_id}\n  A: {p.a_name}: {p.a_summary}\n  B: {p.b_name}: {p.b_summary}" for p in pairs]
        return self._structured("\n".join(lines), SameConceptJudgments, prompts.JUDGE_SAME)

    def judge_coverage(self, requests: list[CoverageRequest]) -> CoverageJudgments:
        blocks = []
        for r in requests:
            passages = "\n".join(f"  [{p.label}] ({p.source}) {p.text[:700]}" for p in r.passages) or "  (no passages)"
            blocks.append(f"concept_id={r.concept_id} | {r.name}: {r.summary}\n  depth needed: {r.depth or 'standard'}\n{passages}")
        return self._structured("\n\n".join(blocks), CoverageJudgments, prompts.JUDGE_COVERAGE)

    def write_packs(self, course_label: str, concepts: list[ConceptCard], catalog: list[ResourceCard]) -> ConceptPacks:
        cat = "\n".join(f"- id={r.id} | {r.title}" + (f" — {r.detail}" if r.detail else "") for r in catalog) or "(empty)"
        blocks = []
        for c in concepts:
            uses = "; ".join(c.how_used[:3])
            blocks.append(f"concept_id={c.id} | {c.name}: {c.summary}\n  depth needed: {c.depth or 'standard'}\n  used for: {uses}")
        contents = "Resource catalog:\n" + cat + "\n\nConcepts:\n" + "\n".join(blocks)
        return self._structured(contents, ConceptPacks, prompts.WRITE_PACKS.format(course=course_label))

    def solve(self, questions: list[QuestionCard]) -> Solutions:
        blocks = []
        for q in questions:
            opts = "\n".join(f"  {i}. {c}" for i, c in enumerate(q.choices))
            blocks.append(f"question_id={q.id}\n{q.prompt}\n{opts}")
        return self._structured("\n\n".join(blocks), Solutions, prompts.SOLVE)

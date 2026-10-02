"""The AI engine interface.

Each method is one well-defined job with a typed result. GeminiEngine does the work with Gemini;
OfflineEngine runs deterministic heuristics so tests and no-network demos still exercise every
pipeline end to end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .schemas import ConceptPacks, CoverageJudgments, MappingResult, SameConceptJudgments, Solutions, SyllabusParse


class EngineUnavailable(RuntimeError):
    """Raised when a job needs Gemini (e.g. reading a scanned PDF) but only the offline engine is active."""


@dataclass
class ItemCard:
    id: str
    week: int
    date: str | None
    title: str
    details: str = ""
    kind: str = "lecture"


@dataclass
class ConceptCard:
    id: str
    name: str
    summary: str = ""
    depth: str = ""
    how_used: list[str] = field(default_factory=list)
    hidden: bool = False


@dataclass
class ResourceCard:
    id: str
    title: str
    detail: str = ""
    subjects: list[str] = field(default_factory=list)


@dataclass
class QuestionCard:
    id: str
    prompt: str
    choices: list[str]


@dataclass
class PairCard:
    pair_id: str
    a_name: str
    a_summary: str
    b_name: str
    b_summary: str


@dataclass
class EvidencePassage:
    label: str
    source: str
    text: str


@dataclass
class CoverageRequest:
    concept_id: str
    name: str
    summary: str
    depth: str
    passages: list[EvidencePassage]


@dataclass
class CourseContext:
    """Everything the mapper knows about a course besides the timeline itself."""

    label: str
    prereq_text: str = ""
    official_prereqs: list[str] = field(default_factory=list)
    informal_requirements: list[str] = field(default_factory=list)
    instructor_notes: list[str] = field(default_factory=list)
    taught_here: list[str] = field(default_factory=list)
    bulletin: list[str] = field(default_factory=list)  # "DS 212 Business Statistics: <description>"


class Engine(Protocol):
    online: bool
    label: str

    def read_document(self, data: bytes, mime: str, filename: str) -> str: ...

    def parse_syllabus(self, text: str, hint_code: str) -> SyllabusParse: ...

    def map_prerequisites(self, ctx: CourseContext, items: list[ItemCard], known: list[str], sample: int = 0) -> MappingResult: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def judge_same(self, pairs: list[PairCard]) -> SameConceptJudgments: ...

    def judge_coverage(self, requests: list[CoverageRequest]) -> CoverageJudgments: ...

    def write_packs(self, course_label: str, concepts: list[ConceptCard], catalog: list[ResourceCard]) -> ConceptPacks: ...

    def solve(self, questions: list[QuestionCard]) -> Solutions: ...

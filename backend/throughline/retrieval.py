"""Evidence retrieval: what did the listed prerequisites actually teach?

The corpus for one course is built from:
  - SF State Bulletin descriptions of the listed prerequisites,
  - syllabi of those prerequisites (uploaded alongside, or already mapped by another student),
  - this syllabus's own notes about what students need.
Search is hybrid: BM25 for exact terms and embeddings for paraphrases, fused with reciprocal rank fusion.
The model then judges coverage using only the retrieved passages, and code checks that the quote it
returns really appears in the passage it cites.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from .llm import Engine, EvidencePassage
from .models import Course
from .repo import Catalog, CourseRepo
from .store import Store
from .textutil import BM25, course_code, hashed_embedding, rrf, tokens

log = logging.getLogger(__name__)

CHUNK_CHARS = 240  # roughly one schedule row per passage, so quotes point at a specific week


@dataclass
class Passage:
    label: str
    source: str  # human-readable, e.g. "DS 212 syllabus, week 9"
    text: str
    kind: str  # bulletin | prereq_syllabus | this_syllabus
    code: str | None  # course the passage describes (None for this syllabus)

    def card(self) -> EvidencePassage:
        return EvidencePassage(self.label, self.source, self.text)


def chunk_lines(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Pack consecutive non-empty lines into chunks of about `limit` characters (schedules stay row-aligned)."""
    chunks, cur = [], ""
    for line in (l.strip() for l in text.splitlines()):
        if not line:
            continue
        if cur and len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur = f"{cur} | {line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def build_corpus(store: Store, course: Course) -> list[Passage]:
    own = course_code(course.code)
    listed = {course_code(c) for c in course.official_prereqs}
    passages: list[Passage] = []

    def add(source: str, text: str, kind: str, code: str | None) -> None:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 20:
            passages.append(Passage(f"p{len(passages) + 1}", source, text, kind, code))

    for b in course.bulletin:
        code = course_code(b.code)
        if code != own and (code in listed or not listed):
            add(f"Bulletin: {code} {b.title}", f"{code} {b.title}. {b.description}", "bulletin", code)
    for doc in course.prereq_docs:
        for chunk in chunk_lines(doc.text):
            add(f"{course_code(doc.code)} syllabus", chunk, "prereq_syllabus", course_code(doc.code))
    # Prerequisite courses another student already mapped: their timelines say what they covered.
    catalog = Catalog(store)
    for other in catalog.courses.list():
        code = course_code(other.code)
        if other.id == course.id or code not in listed or other.build.status != "ready":
            continue
        for t in CourseRepo(store, other.id).topics.list():
            add(f"{code} syllabus, week {t.week}", f"{t.title}. {t.details}", "prereq_syllabus", code)
    for note in [*course.instructor_notes, *course.informal_requirements]:
        add("This syllabus", note, "this_syllabus", None)
    return passages


class EvidenceIndex:
    def __init__(self, engine: Engine, passages: list[Passage]):
        self.passages = passages
        self.bm25 = BM25([p.text for p in passages])
        self.vectors = None
        if passages:
            texts = [p.text for p in passages]
            try:
                vecs = engine.embed(texts)
            except Exception as exc:
                log.warning("embedding failed for evidence index, using lexical vectors: %s", exc)
                vecs = [hashed_embedding(t) for t in texts]
            m = np.asarray(vecs, dtype=np.float32)
            self.vectors = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        self.engine = engine

    def search(self, query: str, query_vec: list[float] | None, k: int = 4) -> list[Passage]:
        if not self.passages:
            return []
        lexical = self.bm25.scores(query)
        lex_rank = [i for i in np.argsort(-np.asarray(lexical)) if lexical[i] > 0]
        rankings = [lex_rank]
        if self.vectors is not None and query_vec is not None:
            q = np.asarray(query_vec, dtype=np.float32)
            q /= max(float(np.linalg.norm(q)), 1e-9)
            sims = self.vectors @ q
            rankings.append([int(i) for i in np.argsort(-sims)[: max(k * 3, 8)]])
        fused = rrf(rankings)
        return [self.passages[i] for i, _ in fused[:k]]


def quote_supported(quote: str, passage: str, threshold: float = 0.6) -> bool:
    """True when most of the quote's words appear in the passage (models paraphrase; we require near-verbatim)."""
    q = tokens(quote)
    if not q:
        return False
    have = set(tokens(passage))
    return sum(1 for t in q if t in have) / len(q) >= threshold

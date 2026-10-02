"""A student's own materials from a prerequisite course (notes, slides, handouts).

Read page by page or slide by slide, so every match can point to where it is ("slide 14"). For each concept in
the course map, retrieve the closest passages (BM25 + embeddings), let the model judge from those passages only
whether they cover the concept, and keep a match only when its quote is really in the passage.
Materials are private: only the student who uploaded them sees them or their matches.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

from .ingest import IMAGE_MIMES, TEXT_EXTS, UnsupportedFile, _docx_text, _html_text
from .llm import Engine, EngineUnavailable
from .llm.base import CoverageRequest
from .models import Concept, Material, MaterialChunk, MaterialMatch
from .retrieval import EvidenceIndex, Passage, quote_supported
from .textutil import course_code, redact

log = logging.getLogger(__name__)

CHUNK_CHARS = 500
MAX_CHARS = 120_000  # per file; keeps one stored document well under Firestore's 1 MB
PER_CALL = 6
KIND_WORD = {"slides": "slides", "pdf": "PDF", "notes": "notes", "doc": "document", "photo": "photo"}


def _slide_no(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _xml_text(xml: str) -> str:
    xml = re.sub(r"</a:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def pptx_sections(data: bytes) -> list[tuple[str, str]]:
    """One section per slide, speaker notes included."""
    import html

    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_slide_no)
        for name in slides:
            n = _slide_no(name)
            text = _xml_text(z.read(name).decode("utf-8", errors="replace"))
            notes_name = f"ppt/notesSlides/notesSlide{n}.xml"
            if notes_name in names:
                text += "\n" + _xml_text(z.read(notes_name).decode("utf-8", errors="replace"))
            text = html.unescape(text).strip()
            if text:
                out.append((f"slide {n}", text))
    return out


def pdf_sections(data: bytes) -> list[tuple[str, str]]:
    from pypdf import PdfReader

    out = []
    for i, page in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            out.append((f"page {i}", text))
    return out


def text_sections(text: str, unit: str = "section") -> list[tuple[str, str]]:
    """Split plain text into numbered sections of about 1,200 characters at blank lines."""
    blocks, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if cur and len(cur) + len(para) > 1200:
            blocks.append(cur)
            cur = ""
        cur = f"{cur}\n{para}" if cur else para
    if cur:
        blocks.append(cur)
    return [(f"{unit} {i}", b) for i, b in enumerate(blocks, start=1)]


def read_material(engine: Engine, data: bytes, filename: str, mime: str) -> tuple[str, list[tuple[str, str]]]:
    """(kind, [(location, text)]) for a supported file; Gemini reads scans and photos."""
    name = (filename or "").lower()
    if name.endswith((".ppt", ".doc")) and not name.endswith((".pptx", ".docx")):
        raise UnsupportedFile("Old .ppt and .doc files can't be read. Save them as .pptx, .docx or PDF.")
    if name.endswith(".pptx"):
        return "slides", pptx_sections(data)
    if name.endswith(".docx"):
        return "doc", text_sections(_docx_text(data))
    if name.endswith(TEXT_EXTS) or mime.startswith("text/"):
        raw = data.decode("utf-8", errors="replace")
        return "notes", text_sections(_html_text(raw) if name.endswith((".html", ".htm")) else raw)
    if name.endswith(".pdf") or mime == "application/pdf":
        sections = pdf_sections(data)
        if sum(len(t) for _, t in sections) >= 200:
            return "pdf", sections
        mime = "application/pdf"  # scanned: let the model read it
    elif not mime.startswith(IMAGE_MIMES):
        raise UnsupportedFile("Upload notes as PDF, PowerPoint (.pptx), Word (.docx), text, or a photo.")
    try:
        text = engine.read_document(data, mime, filename)
    except EngineUnavailable as exc:
        raise UnsupportedFile(str(exc)) from exc
    return ("pdf" if mime == "application/pdf" else "photo"), text_sections(text, unit="part")


def to_chunks(sections: list[tuple[str, str]]) -> list[MaterialChunk]:
    """Split each section into passages of about CHUNK_CHARS, keeping its location; redact personal details."""
    chunks, total = [], 0
    for loc, text in sections:
        lines = [l.strip() for l in redact(text).splitlines() if l.strip()]
        cur = ""
        for line in lines:
            if cur and len(cur) + len(line) + 3 > CHUNK_CHARS:
                chunks.append(MaterialChunk(loc=loc, text=cur))
                total += len(cur)
                cur = ""
            cur = f"{cur} | {line}" if cur else line
        if cur:
            chunks.append(MaterialChunk(loc=loc, text=cur))
            total += len(cur)
        if total >= MAX_CHARS:
            break
    return chunks


def match_concepts(engine: Engine, concepts: list[Concept], material: Material) -> list[MaterialMatch]:
    """Which concepts this material covers, and where; each match carries a quote verified against its passage."""
    if not concepts or not material.chunks:
        return []
    source = f"{material.prereq_code or 'Your'} {KIND_WORD.get(material.kind, 'notes')}".strip()
    passages = [Passage(label=f"n{i}", source=f"{source}, {ch.loc}", text=ch.text, kind="notes", code=material.prereq_code or None)
                for i, ch in enumerate(material.chunks)]
    loc_of = {p.label: ch.loc for p, ch in zip(passages, material.chunks)}
    index = EvidenceIndex(engine, passages)
    queries = [f"{c.name}. {' '.join(c.aliases[:3])}. {c.summary}" for c in concepts]
    try:
        qvecs = engine.embed(queries)
    except Exception:
        qvecs = [None] * len(concepts)

    requests, retrieved = [], {}
    for c, q, qv in zip(concepts, queries, qvecs):
        hits = index.search(q, qv, k=3)
        retrieved[c.id] = {p.label: p for p in hits}
        requests.append(CoverageRequest(concept_id=c.id, name=c.name, summary=c.summary, depth=c.depth,
                                        passages=[p.card() for p in hits]))
    batches = [requests[i : i + PER_CALL] for i in range(0, len(requests), PER_CALL)]

    def judge(batch):
        try:
            return engine.judge_coverage(batch).judgments
        except Exception as exc:
            log.warning("judging material coverage failed: %s", exc)
            return []

    matches = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for judgments in pool.map(judge, batches):
            for j in judgments:
                cited = retrieved.get(j.concept_id, {}).get(j.passage or "")
                if j.verdict == "unrelated" or cited is None or not quote_supported(j.quote, cited.text):
                    continue
                matches.append(MaterialMatch(concept_id=j.concept_id, loc=loc_of[cited.label], quote=j.quote.strip()[:300],
                                             verdict=j.verdict))
    return matches


def build_material(engine: Engine, concepts: list[Concept], student: str, prereq_code: str, filename: str,
                   data: bytes, mime: str) -> Material:
    kind, sections = read_material(engine, data, filename, mime)
    chunks = to_chunks(sections)
    if not chunks:
        raise UnsupportedFile("No text found in that file. If it's a scan, try a clearer photo or a PDF.")
    material = Material(student=student, prereq_code=course_code(prereq_code) if prereq_code.strip() else "",
                        filename=(filename or "notes")[:120], kind=kind, chunks=chunks)
    material.matches = match_concepts(engine, concepts, material)
    return material

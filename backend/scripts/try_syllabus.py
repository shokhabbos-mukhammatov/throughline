"""Run the course-map pipeline on local syllabus files and print what it found. Nothing is saved.

Usage (from backend/, with GEMINI_API_KEY set for the real thing):
    python scripts/try_syllabus.py "DS 612" ../private/ds612.docx
    python scripts/try_syllabus.py "CSC 648" ../private/csc648.pdf --questions

Keep real syllabi in ../private/ (git-ignored): they are course materials.
"""

from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PERSIST", "0")

from throughline.config import Settings  # noqa: E402
from throughline.ctx import Ctx  # noqa: E402
from throughline.ingest import syllabus_text  # noqa: E402
from throughline.llm import make_engine  # noqa: E402
from throughline.mapping import build_course  # noqa: E402
from throughline.models import Course  # noqa: E402
from throughline.store.memory import MemoryStore  # noqa: E402
from throughline.textutil import redact  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code")
    ap.add_argument("path")
    ap.add_argument("--questions", action="store_true", help="print every generated question")
    args = ap.parse_args()

    settings = Settings()
    engine = make_engine(settings)
    print(f"Engine: {engine.label}   Bulletin live: {settings.bulletin_live}\n")
    with open(args.path, "rb") as fh:
        data = fh.read()
    mime = mimetypes.guess_type(args.path)[0] or "application/octet-stream"
    text = redact(syllabus_text(engine, data, os.path.basename(args.path), mime))

    ctx = Ctx(store=MemoryStore(), engine=engine, settings=settings)
    course = Course(owner="cli", code=args.code, syllabus_text=text)
    ctx.catalog.put(course)
    t0 = time.time()
    build_course(ctx, course.id, args.code)
    course = ctx.catalog.get(course.id)
    repo = ctx.course(course.id)
    print(f"Build: {course.build.status} in {time.time() - t0:.1f}s {course.build.error or ''}")
    if course.build.status != "ready":
        return
    print(f"{course.code} {course.title} | {course.term} | timeline: {course.timeline_kind} | term start {course.term_start}")
    print(f"Prerequisites: {course.prereq_text}  routes={course.prereq_routes}")
    print(f"AI policy: {course.ai_policy.stance}: {course.ai_policy.summary}")
    for b in course.bulletin:
        print(f"Bulletin [{b.source}] {b.code} {b.title}: {b.prerequisites}")
    for note in course.instructor_notes + course.informal_requirements:
        print(f"Note: {note}")

    concepts = {c.id: c for c in repo.concepts.list()}
    reqs = repo.requirements.list()
    print("\nTimeline")
    for t in sorted(repo.topics.list(), key=lambda t: (t.week, t.date or t.week)):
        needs = [concepts[r.concept_id].name for r in reqs if r.topic_id == t.id]
        flag = " (est.)" if t.estimated else ""
        print(f"  wk {t.week:>2} {t.date or '':<10}{flag} {t.kind[:4]} | {t.title[:60]:<60} <- {', '.join(needs) or '-'}")

    qs = repo.questions.list()
    print("\nConcepts")
    for c in concepts.values():
        mine = [q for q in qs if q.concept_id == c.id]
        flagged = sum(1 for q in mine if q.verification == "disagreed")
        where = f"covered by {c.covered_by}" if c.covered_by else "HIDDEN (no listed prerequisite)"
        print(f"  {c.name:<40} {where:<34} {len(mine)} q, {flagged} disputed, {len(c.resources)} resources")
        print(f"      depth: {c.depth} | evidence: {c.evidence[:120]}")
        if args.questions:
            for q in mine:
                print(f"      [{q.verification}] {q.prompt[:100]} -> {q.choices[q.correct_index][:60]}")


if __name__ == "__main__":
    main()

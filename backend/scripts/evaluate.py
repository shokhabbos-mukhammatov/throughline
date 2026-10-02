"""Evaluate the course-map pipeline against gold labels.

For each gold file in eval/gold/, run the full pipeline on the matching syllabus and report:
  recall      required prerequisites found / required prerequisites
  precision   found concepts that are required or acceptable / found concepts (foundations excluded)
  taught      found concepts the course teaches itself (errors)
  week        required ones whose first-needed week is within 1 (2 for estimated timelines) of the gold week
  coverage    exact agreement of listed / likely / missing / unknown with the gold label
plus the timeline kind, model calls per job, time, and the share of generated questions whose answer key
an independent solve disputed.

Usage (from backend/):
    python scripts/evaluate.py --files ../private                # all gold files whose syllabus is present
    python scripts/evaluate.py --files ../private --only ds612   # one course
Results are printed as a table and saved to <files>/eval-results-<timestamp>.json (git-ignored with private/).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("PERSIST", "0")

from throughline.config import Settings  # noqa: E402
from throughline.ctx import Ctx  # noqa: E402
from throughline.ingest import syllabus_text  # noqa: E402
from throughline.llm import make_engine  # noqa: E402
from throughline.mapping import build_course  # noqa: E402
from throughline.models import Course, PrereqDoc  # noqa: E402
from throughline.seed import library, sample  # noqa: E402
from throughline.store.memory import MemoryStore  # noqa: E402
from throughline.textutil import jaccard, normalize_name, redact, tokens  # noqa: E402

GOLD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "gold")


def names_of(entry) -> list[str]:
    if isinstance(entry, str):
        return [entry]
    return [entry["name"], *entry.get("aliases", [])]


def matches(predicted: list[str], gold: list[str]) -> bool:
    """Same concept if any spelling agrees: normalized equality, the library's alias table, or strong word overlap."""
    for p in predicted:
        lib_p = library.find(p)
        for g in gold:
            if normalize_name(p) == normalize_name(g):
                return True
            if lib_p is not None and lib_p is library.find(g):
                return True
            tp, tg = set(tokens(p)), set(tokens(g))
            if tp and tg and (jaccard(p, g) >= 0.6 or (len(tg) >= 2 and tg <= tp) or (len(tp) >= 2 and tp <= tg)):
                return True
    return False


def load_text(engine, path: str) -> str:
    with open(path, "rb") as fh:
        data = fh.read()
    return syllabus_text(engine, data, os.path.basename(path), mimetypes.guess_type(path)[0] or "application/octet-stream")


def evaluate_one(gold: dict, files: str, settings: Settings) -> dict | None:
    engine = make_engine(settings)
    if gold["file"] == "@sample":
        text = sample.syllabus_text(sample.term_start(datetime.now().date()))
        docs = [PrereqDoc(code="DEMO 212", text=sample.DEMO_212_SYLLABUS)]
    else:
        path = os.path.join(files, gold["file"])
        if not os.path.exists(path):
            return None
        text = load_text(engine, path)
        docs = []
        for p in gold.get("prereq_files", []):
            pp = os.path.join(files, p["file"])
            if os.path.exists(pp):
                docs.append(PrereqDoc(code=p["code"], text=redact(load_text(engine, pp))))

    ctx = Ctx(store=MemoryStore(), engine=engine, settings=settings)
    course = Course(owner="eval", code=gold["code"], syllabus_text=redact(text), prereq_docs=docs)
    ctx.catalog.put(course)
    t0 = time.time()
    build_course(ctx, course.id, gold["code"])
    seconds = time.time() - t0
    course = ctx.catalog.get(course.id)
    repo = ctx.course(course.id)
    calls: dict[str, int] = {}
    for t in course.build.trace:
        for k, v in t.calls.items():
            calls[k] = calls.get(k, 0) + v
    result = {"code": gold["code"], "status": course.build.status, "error": course.build.error, "seconds": round(seconds, 1), "calls": calls,
              "engine": engine.label}
    if course.build.status != "ready":
        return result

    topics = {t.id: t for t in repo.topics.list()}
    every = repo.concepts.list()
    concepts = [c for c in every if not c.foundation]
    first_week: dict[str, int] = {}
    for r in repo.requirements.list():
        if r.topic_id in topics:
            w = topics[r.topic_id].week
            first_week[r.concept_id] = min(first_week.get(r.concept_id, w), w)
    spellings = {c.id: [c.name, *c.aliases] for c in every}

    required = gold["required"]
    acceptable = [names_of(a) for a in gold.get("acceptable", [])]
    taught = [names_of(t) for t in gold.get("taught_here", [])]
    tolerance = 2 if gold.get("timeline_kind") == "estimated" else 1

    found, week_ok, week_n, cov_ok, cov_n, misses, as_foundation, cov_wrong = 0, 0, 0, 0, 0, [], [], []
    for g in required:
        # A foundation (added because something found builds on it) still reaches the student's plan,
        # so it counts for recall; it has no week of its own, so week accuracy skips it.
        hit = next((c for c in concepts if matches(spellings[c.id], names_of(g))), None) \
            or next((c for c in every if c.foundation and matches(spellings[c.id], names_of(g))), None)
        if hit is None:
            misses.append(g["name"])
            continue
        found += 1
        if hit.foundation:
            as_foundation.append(g["name"])
        if "week" in g and hit.id in first_week:
            week_n += 1
            week_ok += abs(first_week[hit.id] - g["week"]) <= tolerance
        if "coverage" in g:
            cov_n += 1
            cov_ok += hit.coverage == g["coverage"]
            if hit.coverage != g["coverage"]:
                cov_wrong.append(f"{g['name']}: map says {hit.coverage}, label says {g['coverage']}")

    good, wrong_taught, extra = 0, [], []
    for c in concepts:
        sp = spellings[c.id]
        if any(matches(sp, names_of(g)) for g in required) or any(matches(sp, a) for a in acceptable):
            good += 1
        elif any(matches(sp, t) for t in taught):
            wrong_taught.append(c.name)
        else:
            extra.append(c.name)

    qs = repo.questions.list()
    recall = found / len(required) if required else 1.0
    precision = good / len(concepts) if concepts else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    result.update({
        "timeline_kind": course.timeline_kind, "timeline_ok": course.timeline_kind == gold.get("timeline_kind", course.timeline_kind),
        "concepts": len(concepts), "foundations": sum(1 for c in repo.concepts.list() if c.foundation), "edges": len(repo.edges.list()),
        "recall": round(recall, 3), "precision": round(precision, 3), "f1": round(f1, 3),
        "week_acc": round(week_ok / week_n, 3) if week_n else None, "coverage_acc": round(cov_ok / cov_n, 3) if cov_n else None,
        "missed": misses, "found_as_foundation": as_foundation, "coverage_mismatches": cov_wrong, "taught_here_errors": wrong_taught, "unlabeled": extra,
        "questions": len(qs), "disputed": round(sum(q.verification == "disagreed" for q in qs) / len(qs), 3) if qs else None,
    })
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", default=os.path.join("..", "private"), help="folder with the syllabus files named in the gold labels")
    ap.add_argument("--gold", default=GOLD_DIR)
    ap.add_argument("--only", default="", help="substring of a gold file name")
    args = ap.parse_args()
    if not os.path.isdir(args.files):
        print(f"No folder {args.files}. Put the syllabi named in eval/gold/*.json there (it stays out of git).")
        return 2
    settings = Settings()

    results = []
    for name in sorted(os.listdir(args.gold)):
        if not name.endswith(".json") or args.only not in name:
            continue
        with open(os.path.join(args.gold, name), encoding="utf-8") as fh:
            gold = json.load(fh)
        print(f"… {gold['code']} ({gold['file']})", flush=True)
        r = evaluate_one(gold, args.files, settings)
        if r is None:
            print(f"   skipped: {gold['file']} not found in {args.files}")
            continue
        results.append(r)

    if not results:
        print("No syllabi found. Put them in the --files folder with the names used in eval/gold/*.json.")
        return 1
    print(f"\n{'course':<10} {'status':<6} {'recall':>6} {'prec':>6} {'F1':>6} {'week':>6} {'cover':>6} {'kind':>5} {'disp':>6} {'calls':>6} {'sec':>6}")
    for r in results:
        if r["status"] != "ready":
            print(f"{r['code']:<10} {r['status']:<6} {r['error']}")
            continue
        fmt = lambda v: "-" if v is None else f"{v:.2f}"
        print(f"{r['code']:<10} {'ok':<6} {fmt(r['recall']):>6} {fmt(r['precision']):>6} {fmt(r['f1']):>6} {fmt(r['week_acc']):>6} "
              f"{fmt(r['coverage_acc']):>6} {'yes' if r['timeline_ok'] else 'no':>5} {fmt(r['disputed']):>6} {sum(r['calls'].values()):>6} {r['seconds']:>6}")
        if r["missed"]:
            print(f"           missed: {', '.join(r['missed'])}")
        for m in r.get("coverage_mismatches", []):
            print(f"           coverage: {m}")
        if r.get("found_as_foundation"):
            print(f"           found only as a foundation (no week): {', '.join(r['found_as_foundation'])}")
        if r["taught_here_errors"]:
            print(f"           listed but taught in the course: {', '.join(r['taught_here_errors'])}")
        if r["unlabeled"]:
            print(f"           not in the labels (review: add to acceptable or fix the map): {', '.join(r['unlabeled'])}")
    ok = [r for r in results if r["status"] == "ready"]
    if ok:
        mean = lambda k: sum(r[k] for r in ok if r[k] is not None) / max(1, sum(1 for r in ok if r[k] is not None))
        print(f"\nMean over {len(ok)} course(s): recall {mean('recall'):.2f}, precision {mean('precision'):.2f}, F1 {mean('f1'):.2f}, "
              f"week {mean('week_acc'):.2f}, coverage {mean('coverage_acc'):.2f}")
    out = os.path.join(args.files, f"eval-results-{datetime.now():%Y%m%d-%H%M%S}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"engine": results[0].get("engine"), "results": results}, fh, indent=2)
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

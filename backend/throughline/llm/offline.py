"""Deterministic stand-in for Gemini.

It powers the test suite and keeps the app usable without network access. Its results are visibly
cruder: regular expressions read the schedule, keyword lists from the concept library stand in for
prerequisite reasoning, and question packs come only from the hand-written library. The UI labels
this mode.
"""

from __future__ import annotations

import re
from datetime import date

from ..seed import library
from ..textutil import contains_phrase, course_code, hashed_embedding, jaccard, normalize_name, prereq_groups
from .base import ConceptCard, CourseContext, CoverageRequest, EngineUnavailable, ItemCard, PairCard, QuestionCard, ResourceCard, RevisionContext
from .schemas import (
    ConceptPack,
    ConceptPacks,
    CoverageJudgment,
    CoverageJudgments,
    Foundation,
    FreeResource,
    GeneratedQuestion,
    ItemRequirements,
    MapChange,
    MappingResult,
    NeedRef,
    PairJudgment,
    PrereqGroup,
    RequiredConcept,
    RevisionPlan,
    SameConceptJudgments,
    SourceQuestion,
    Solutions,
    SyllabusParse,
    TimelineItem,
)

_CODE = re.compile(r"\b([A-Z]{2,5})\s?-?(\d{3}[A-Z]?)\b")
_TERM = re.compile(r"\b(Fall|Spring|Summer|Winter)\s+(20\d\d)\b", re.IGNORECASE)
_ISO = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_MON_DAY = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2})\b")
_WEEK_LINE = re.compile(r"^\W*(?:week|wk)\.?\s*(\d{1,2})\b[\s:.\-–—|)(]*(.*)$", re.IGNORECASE)
_TABLE_LINE = re.compile(r"^\s*(\d{1,2})(?:\t|\s{2,})(\S.*)$")
_CELL_SPLIT = re.compile(r"\s*\|\s*|\s{3,}|\t")
_AI_MENTION = re.compile(r"\b(AI|GenAI|generative|ChatGPT|artificial intelligence|Al)\b")
_QUIZ_LINE = re.compile(r"^\W*((?:quiz|exam|midterm|test)\s*\d*)\s*[·:\-–—|]?\s*(.*)$", re.IGNORECASE)
_NOT_NEEDED = re.compile(r"\b(remove|drop|delete|(?:is|are|isn't|aren't)?\s*not (?:needed|required|used|covered)|"
                         r"(?:isn't|aren't) (?:needed|required|used|covered)|(?:doesn't|does not|don't|do not) need|no need)\b", re.IGNORECASE)
# "3. Prompt? A) one B) two C) three D) four Answer: B", one option per line or all on one line
_MC = re.compile(r"(?:^|\n)\s*(?:Q(?:uestion)?\s*)?\d{1,2}[.):]\s*(?P<q>[^\n]+?)\s*(?:\n|\s)\s*[Aa][.)]\s*(?P<a>[^\n]+?)\s*(?:\n|\s)\s*[Bb][.)]\s*(?P<b>[^\n]+?)"
                 r"\s*(?:\n|\s)\s*[Cc][.)]\s*(?P<c>[^\n]+?)\s*(?:\n|\s)\s*[Dd][.)]\s*(?P<d>[^\n]+?)\s*(?:\n\s*(?:Answer|Key)\s*[:=]\s*(?P<key>[A-Da-d]))?(?=\n|$)")
_SKIP_TITLES = ("spring break", "thanksgiving", "no class", "holiday", "no sessions")


def _date_in(text: str, year: int | None) -> date | None:
    iso = _ISO.search(text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    md = _MON_DAY.search(text)
    if md and year:
        try:
            return date(year, _MONTHS[md.group(1).lower()[:3]], int(md.group(2)))
        except ValueError:
            return None
    return None


def _clean(text: str) -> str:
    text = _ISO.sub("", text)
    text = _MON_DAY.sub("", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"^[\s)|:\-–—]+", "", text)  # "Week 3 (2026-11-16): Topic" leaves "): Topic" once the date is gone
    return re.sub(r"\s{2,}", " ", text).strip(" |:-–—")


class OfflineEngine:
    online = False
    label = "Offline heuristics (no Gemini)"

    def read_document(self, data: bytes, mime: str, filename: str) -> str:
        raise EngineUnavailable(f"Reading {filename} ({mime}) needs Gemini. Upload a text-based PDF, .docx or text file instead.")
    def parse_syllabus(self, text: str, hint_code: str) -> SyllabusParse:
        lines = [l.rstrip() for l in text.splitlines()]
        code_match = _CODE.search(text)
        code = course_code(hint_code) if hint_code else (f"{code_match.group(1)} {code_match.group(2)}" if code_match else "COURSE")
        title = ""
        for line in lines[:8]:
            stripped = line.strip("# ").strip()
            if stripped and code.split(" ")[-1] in stripped:
                title = _CODE.sub("", stripped).strip(" :—–-|·")
                title = re.split(r"\s{2,}|·|\|", title)[0].strip()
                if title:
                    break
        term_match = _TERM.search(text)
        term = f"{term_match.group(1).title()} {term_match.group(2)}" if term_match else ""
        year = int(term_match.group(2)) if term_match else None

        prereq_text, prereqs, routes, informal, notes = "", [], [], [], []
        own_number = code.split(" ")[-1]
        for line in lines:
            low = line.lower()
            other_course = re.search(r"prerequisites?\s+for\s+([A-Z]{2,5}\s*\d{3})", line, re.IGNORECASE)
            if other_course and own_number not in other_course.group(1):
                continue  # a cross-listed section's prerequisite line, not this course's
            if "prerequisite" in low and not prereq_text:
                prereq_text = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                required_part = re.split(r"\brecommended\b", line, flags=re.IGNORECASE)[0]
                required_part = re.sub(r"[^.;]*$", "", required_part) if "recommended" in low else required_part
                prereqs = [f"{a} {b}" for a, b in _CODE.findall(required_part) if f"{a} {b}" != code]
                for route in ("or equivalent", "permission of the instructor", "consent of the instructor", "graduate standing"):
                    if route in low:
                        routes.append(route)
            if len(line) > 300:
                continue
            if re.search(r"\b(experience|familiarity|background)( \w+){0,2} (is|are) required\b", low):
                informal.append(line.strip(" -•*"))
            if re.search(r"you do not need (any )?(prior|linear|calculus|statistics|programming|to know)|no prior (knowledge|experience|coursework)|expected to (know|be comfortable)|"
                         r"should be comfortable|assumes? (familiarity|knowledge)|background is required", low):
                notes.append(line.strip(" -•*"))

        stance, ai_summary = "unknown", ""
        # Join each line with the next: PDF text often breaks a policy sentence across lines.
        pairs = [f"{a.strip()} {b.strip()}" for a, b in zip(lines, lines[1:] + [""])]
        policy = [p for p in pairs if _AI_MENTION.search(p) and re.search(
            r"prohibit|not permitted|not allowed|encourage|allowed|may use|may be used|permitted|must cite|disclose", p, re.IGNORECASE)]
        if policy:
            joined = " ".join(policy).lower()
            banned = re.search(r"prohibit|not permitted|not allowed", joined)
            allowed = re.search(r"encourage|(?<!not )allowed|may use|may be used|(?<!not )permitted", joined)
            stance = "prohibited" if banned and not allowed else "encouraged" if "encourage" in joined and not banned else "limited"
            ai_summary = next((l for l in policy if re.search(r"prohibit|encourage", l, re.IGNORECASE)), policy[0])[:240]

        items: list[TimelineItem] = []
        kind = "estimated"
        for i, line in enumerate(lines):
            week_match = _WEEK_LINE.match(line) or _TABLE_LINE.match(line)
            if week_match:
                week = int(week_match.group(1))
                rest = week_match.group(2)
                when = _date_in(rest, year)
                cells = [_clean(c) for c in _CELL_SPLIT.split(rest)]
                cells = [c for c in cells if c]
                if not cells or week > 20:
                    continue
                title = cells[0]
                if any(s in title.lower() for s in _SKIP_TITLES):
                    continue
                items.append(TimelineItem(week=week, date=when.isoformat() if when else None, title=title,
                                          details="; ".join(cells[1:]), kind="lecture"))
                continue
            quiz = _QUIZ_LINE.match(line)
            if quiz and _date_in(line, year) and "makeup" not in line.lower():
                when = _date_in(line, year)
                covers = _clean(quiz.group(2))
                if not covers and i + 1 < len(lines):
                    covers = lines[i + 1].strip()
                items.append(TimelineItem(week=0, date=when.isoformat() if when else None, title=quiz.group(1).title(),
                                          details=covers, kind="assessment"))
        lectures = [it for it in items if it.kind == "lecture"]
        if lectures:
            items = lectures
            kind = "dated_weeks" if any(it.date for it in lectures) else "weeks"
        elif items:
            kind = "assessments"
        dedup: dict[tuple, TimelineItem] = {}
        for it in items:
            dedup.setdefault((it.week, it.title), it)
        timeline = list(dedup.values())

        dated = sorted(date.fromisoformat(it.date) for it in timeline if it.date)
        start = None
        if kind == "dated_weeks" and dated:
            first = min(timeline, key=lambda it: (it.week, it.date or "9999"))
            if first.date:
                start = date.fromordinal(date.fromisoformat(first.date).toordinal() - 7 * (first.week - 1))
        elif kind in ("assessments", "weeks"):
            # The earliest date mentioned anywhere (first class, add deadlines) is the best guess at the term start.
            mentioned = [d for d in (_date_in(m.group(0), year) for m in _MON_DAY.finditer(text)) if d]
            start = min([*mentioned, *dated], default=None)
        resources = [FreeResource(title=u, url=u) for u in dict.fromkeys(re.findall(r"https?://[^\s)>\]]+", text))
                     if not re.search(r"sfsu|zoom|instructure|discord|canvas", u, re.IGNORECASE)][:5]
        return SyllabusParse(
            code=code, title=title, term=term, term_start=start.isoformat() if start else None,
            term_end=dated[-1].isoformat() if dated else None, official_prereqs=list(dict.fromkeys(prereqs)),
            prereq_groups=[PrereqGroup(options=g) for g in prereq_groups(prereq_text, prereqs)],
            prereq_text=prereq_text, prereq_routes=routes, informal_requirements=informal[:4], instructor_notes=notes[:4],
            ai_stance=stance, ai_summary=ai_summary, timeline_kind=kind, timeline=timeline, free_resources=resources,
        )
    def map_prerequisites(self, ctx: CourseContext, items: list[ItemCard], known: list[str], sample: int = 0) -> MappingResult:
        bulletin_text = " ".join(ctx.bulletin)
        out = []
        for it in items:
            text = f"{it.title} {it.details}"
            found = []
            for c in library.CONCEPTS:
                if any(contains_phrase(text, k) for k in c.keywords):
                    covering = next((b.split(" ", 2)[0] + " " + b.split(" ", 2)[1] for b in ctx.bulletin
                                     if any(contains_phrase(b, k) for k in c.keywords)), None)
                    found.append(RequiredConcept(
                        name=c.name, summary=c.summary, importance="essential", depth=c.depth,
                        how_used=f"Week {it.week} ({it.title}) builds on {c.name.lower()}.",
                        covered_by=covering,
                        evidence="Matched in the Bulletin description of " + covering if covering else
                        ("No listed prerequisite's Bulletin description mentions it." if bulletin_text else ""),
                        builds_on=[Foundation(name=library.BY_KEY[k].name, summary=library.BY_KEY[k].summary)
                                   for k in library.BUILDS_ON.get(c.key, ())],
                    ))
            out.append(ItemRequirements(item_id=it.id, requires=found[:4]))
        return MappingResult(items=out)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hashed_embedding(t) for t in texts]

    def judge_same(self, pairs: list[PairCard]) -> SameConceptJudgments:
        out = []
        for p in pairs:
            a, b = library.find(p.a_name), library.find(p.b_name)
            same = (a is not None and a is b) or normalize_name(p.a_name) == normalize_name(p.b_name) or jaccard(p.a_name, p.b_name) >= 0.75
            out.append(PairJudgment(pair_id=p.pair_id, same=same, reason="name match" if same else "different names"))
        return SameConceptJudgments(judgments=out)

    def judge_coverage(self, requests: list[CoverageRequest]) -> CoverageJudgments:
        out = []
        for r in requests:
            lib = library.find(r.name)
            phrases = [r.name, *(lib.keywords if lib else ())]
            hit = None
            for p in r.passages:
                for ph in phrases:
                    if contains_phrase(p.text, ph):
                        hit = (p, ph)
                        break
                if hit:
                    break
            if hit:
                p, ph = hit
                quote = next((s.strip() for s in re.split(r"(?<=[.;|])\s+|\s\|\s", p.text) if contains_phrase(s, ph)), p.text)[:200]
                out.append(CoverageJudgment(concept_id=r.concept_id, verdict="teaches" if normalize_name(ph) == normalize_name(r.name) or lib else "partial",
                                            passage=p.label, quote=quote))
            else:
                out.append(CoverageJudgment(concept_id=r.concept_id, verdict="unrelated"))
        return CoverageJudgments(judgments=out)

    def write_packs(self, course_label: str, concepts: list[ConceptCard], catalog: list[ResourceCard]) -> ConceptPacks:
        packs = []
        valid = {r.id for r in catalog}
        for c in concepts:
            lib = library.find(c.name)
            if lib is None:
                continue  # no Gemini and nothing hand-written: the concept stays without questions
            questions = []
            for q in lib.questions:
                choices, idx = library.placed_choices(q, lib.key)
                questions.append(GeneratedQuestion(prompt=q.prompt, choices=choices, correct_index=idx, explanation=q.explanation))
            packs.append(ConceptPack(
                concept_id=c.id, refresher=lib.refresher, learn_outline=lib.learn_outline,
                refresh_minutes=lib.refresh_minutes, learn_minutes=lib.learn_minutes,
                resource_ids=[r for r in lib.resources if r in valid], questions=questions,
            ))
        return ConceptPacks(packs=packs)

    def solve(self, questions: list[QuestionCard]) -> Solutions:
        return Solutions(solutions=[])  # cannot verify without a model; questions stay "unverified"

    def revise_map(self, ctx: RevisionContext) -> RevisionPlan:
        """Keyword rules: "X isn't needed" removes X; a library concept named in the request or the files is added
        (to the weeks whose topics mention it, or a week the sentence names); lettered questions are copied."""
        changes: list[MapChange] = []
        not_done: list[str] = []
        phrases = lambda name: [name, *(library.find(name).keywords if library.find(name) else ())]  # noqa: E731
        sentences = [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", ctx.request) if s.strip()]
        removed: set[str] = set()
        for s in sentences:
            if not _NOT_NEEDED.search(s):
                continue
            for c in ctx.concepts:
                if any(contains_phrase(s, p) for p in phrases(c.name)):
                    changes.append(MapChange(action="remove", concept_id=c.id, reason=f"The request says: {s}"))
                    removed.add(c.id)

        on_map = {normalize_name(c.name) for c in ctx.concepts}
        texts = [(None, s) for s in sentences if not _NOT_NEEDED.search(s)]
        texts += [(p.label, line) for p in ctx.passages for line in p.text.split(" | ")]
        for lib in library.CONCEPTS:
            if normalize_name(lib.name) in on_map:
                continue
            hit = next(((label, t) for label, t in texts for ph in (lib.name, *lib.keywords) if contains_phrase(t, ph)), None)
            if hit is None:
                continue
            label, text = hit
            weeks = [int(w) for w in re.findall(r"\bweeks?\s+(\d{1,2})\b", text, re.IGNORECASE)]
            items = [it for it in ctx.items if it.week in weeks] or [
                it for it in ctx.items if any(contains_phrase(f"{it.title} {it.details}", ph) for ph in (lib.name, *lib.keywords))]
            if not items:
                not_done.append(f"{lib.name} came up, but no week on the timeline says it uses it.")
                continue
            changes.append(MapChange(action="add", name=lib.name, summary=lib.summary, depth=lib.depth,
                                     add_needs=[NeedRef(item_id=it.id, how_used=f"{it.title} relies on it.") for it in items[:3]],
                                     reason="Named in the request." if label is None else "Named in your file.",
                                     source=label, quote=text[:200] if label else ""))
            on_map.add(normalize_name(lib.name))

        questions: list[SourceQuestion] = []
        names = [c.name for c in ctx.concepts if c.id not in removed] + [c.name for c in changes if c.action == "add"]
        for p in ctx.passages:
            for m in _MC.finditer(p.text.replace(" | ", "\n")):
                prompt, opts, key = m.group("q").strip(), [m.group(x).strip() for x in "abcd"], m.group("key")
                about = f"{prompt} {' '.join(opts)}"
                target = next((n for n in names if any(contains_phrase(about, ph) for ph in phrases(n))), None)
                if target:
                    questions.append(SourceQuestion(concept=next((c.id for c in ctx.concepts if c.name == target), target), prompt=prompt,
                                                    choices=opts, correct_index="ABCD".index(key.upper()) if key else 0,
                                                    key_from_file=bool(key), source=p.label))
        found = f"{len(changes)} change{'s' if len(changes) != 1 else ''}, {len(questions)} question{'s' if len(questions) != 1 else ''}"
        return RevisionPlan(summary=f"Offline rules: {found} from the files.",
                            changes=changes, questions=questions[:12], not_done=not_done)

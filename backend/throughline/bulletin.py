"""SF State Bulletin lookup: a course's description and official prerequisites.

The Bulletin (bulletin.sfsu.edu) is a public CourseLeaf catalog with one page per subject, e.g.
/courses/ds/. We fetch a subject page at most once per process (and keep results in the store), parse
the course blocks, and fall back to a small snapshot of entries verified by hand.

Live fetching has not been tested from the development sandbox (sfsu.edu is blocked there); it is
written against CourseLeaf's standard markup and fails soft: no entry, never an exception.
"""

from __future__ import annotations

import logging
import re
import threading

import httpx

from .models import BulletinEntry
from .textutil import course_code

log = logging.getLogger(__name__)

BASE = "https://bulletin.sfsu.edu"
USER_AGENT = "Throughline/0.2 (SF Hacks student project; course prerequisite lookup)"
_CODE = re.compile(r"\b([A-Z]{2,5})\s+(\d{3}[A-Z]?)\b")

# Checked against web search results of the Bulletin. Descriptions are condensed, not quoted.
SNAPSHOT: dict[str, BulletinEntry] = {
    "DS 612": BulletinEntry(
        code="DS 612",
        title="Data Mining with Business Applications",
        description="Modeling and understanding complex datasets with advanced statistical methods; supervised and unsupervised "
        "machine learning techniques; statistical software such as R, SAS, Stata or Python.",
        prerequisites="DS 212/ECON 212 or equivalent; ISYS 263 or passing the waiver exam in basic computer proficiency and "
        "information systems. DS 311 and/or DS 312 recommended.",
        prereq_codes=["DS 212", "ECON 212", "ISYS 263"],
        source="SF State Bulletin (snapshot)",
    ),
    "DS 212": BulletinEntry(
        code="DS 212",
        title="Business Statistics",
        description="Statistical methods essential in solving business problems including probability distributions, estimation "
        "and tests of hypotheses, and regression analysis. Also offered as ECON 212.",
        prerequisites="DS 110 or MATH 108 or MATH 110 or MATH 226 with grades of C- or better.",
        prereq_codes=["DS 110", "MATH 108", "MATH 110", "MATH 226"],
        source="SF State Bulletin (snapshot)",
    ),
    "CSC 648": BulletinEntry(
        code="CSC 648",
        title="Software Engineering",
        prerequisites="Upper-division standing; CSC 317 and CSC 413 with grades of C or better; GPA of 3.0 or higher; "
        "or permission of the instructor.",
        prereq_codes=["CSC 317", "CSC 413"],
        source="SF State Bulletin (snapshot)",
    ),
}
SNAPSHOT["ECON 212"] = SNAPSHOT["DS 212"].model_copy(update={"code": "ECON 212"})

_cache: dict[str, dict[str, BulletinEntry] | None] = {}
_lock = threading.Lock()


def _strip(html: str) -> str:
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#160;", " ")
    return re.sub(r"\s+", " ", text).strip()


def parse_subject_page(html: str, subject: str) -> dict[str, BulletinEntry]:
    """Parse CourseLeaf course blocks into entries keyed by code."""
    entries: dict[str, BulletinEntry] = {}
    blocks = re.split(r'(?i)<div[^>]+class="[^"]*courseblock[^"]*"', html)[1:]
    for block in blocks:
        title_html = re.search(r'(?is)class="[^"]*courseblocktitle[^"]*"[^>]*>(.*?)</p>', block)
        title_text = _strip(title_html.group(1)) if title_html else _strip(block)[:200]
        m = _CODE.search(title_text.replace(" ", " "))
        if not m or m.group(1) != subject:
            continue
        code = f"{m.group(1)} {m.group(2)}"
        title = re.sub(r"\(Units?:.*?\)", "", title_text[m.end():]).strip(" .:-–—")
        body = _strip(block)
        prereq = ""
        # The prerequisite runs until a sentence that starts with an ordinary word (course codes like "DS 311" continue it).
        pm = re.search(r"Prerequisites?:\s*((?:[^.]|\.(?!\s+[A-Z][a-z]))+)", body)
        if pm:
            prereq = pm.group(1).strip().replace("*", "")[:600]
        desc_html = re.search(r'(?is)class="[^"]*courseblockdesc[^"]*"[^>]*>(.*?)</p>', block)
        description = _strip(desc_html.group(1)) if desc_html else ""
        if pm and description:
            description = re.sub(r"Prerequisites?:\s*" + re.escape(pm.group(1).strip()) + r"\.?", "", description).strip(" .")
        codes = [f"{a} {b}" for a, b in _CODE.findall(prereq) if f"{a} {b}" != code]
        entries[code] = BulletinEntry(
            code=code, title=title, description=description[:900], prerequisites=prereq,
            prereq_codes=list(dict.fromkeys(codes)), source="SF State Bulletin (live)",
        )
    return entries


def _fetch_subject(subject: str) -> dict[str, BulletinEntry] | None:
    with _lock:
        if subject in _cache:
            return _cache[subject]
    result: dict[str, BulletinEntry] | None = None
    try:
        resp = httpx.get(f"{BASE}/courses/{subject.lower()}/", headers={"User-Agent": USER_AGENT}, timeout=8.0, follow_redirects=True)
        if resp.status_code == 200:
            result = parse_subject_page(resp.text, subject) or None
    except Exception as exc:  # network blocked, DNS, timeouts: fall back silently
        log.info("Bulletin fetch for %s failed: %s", subject, exc)
    with _lock:
        _cache[subject] = result
    return result


def lookup(code: str, live: bool = True) -> BulletinEntry | None:
    code = course_code(code)
    if live and " " in code:
        live_entries = _fetch_subject(code.split(" ")[0])
        if live_entries and code in live_entries:
            return live_entries[code]
    return SNAPSHOT.get(code)


def chain(code: str, extra: list[str] | None = None, live: bool = True, limit: int = 6) -> list[BulletinEntry]:
    """The course itself plus its direct prerequisites (and any extra codes from the syllabus)."""
    out: list[BulletinEntry] = []
    seen: set[str] = set()
    root = lookup(code, live)
    queue = [code, *(root.prereq_codes if root else []), *(extra or [])]
    for c in queue:
        c = course_code(c)
        if c in seen or len(out) >= limit:
            continue
        seen.add(c)
        entry = root if c == course_code(code) else lookup(c, live)
        if entry:
            out.append(entry)
    return out

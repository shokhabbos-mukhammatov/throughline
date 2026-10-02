"""Check every free-resource link in the concept library, and whether the live SF State Bulletin parses.

Run from a machine with normal internet access (the development sandbox blocks these sites):
    python scripts/check_links.py
"""

from __future__ import annotations

import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from throughline import bulletin  # noqa: E402
from throughline.seed.library import RESOURCES  # noqa: E402


def main() -> int:
    bad = 0
    with httpx.Client(follow_redirects=True, timeout=15, headers={"User-Agent": bulletin.USER_AGENT}) as client:
        for r in RESOURCES:
            try:
                status = client.get(r.url).status_code
            except Exception as exc:
                status = f"error: {exc}"
            ok = status == 200
            bad += not ok
            print(f"{'OK ' if ok else 'BAD'} {status} {r.id:<16} {r.url}")
        try:
            robots = client.get(f"{bulletin.BASE}/robots.txt").text
            print("\nBulletin robots.txt:\n" + robots[:600])
        except Exception as exc:
            print(f"\nBulletin robots.txt unavailable: {exc}")
    for code in ("DS 612", "DS 212", "CSC 648", "CSC 413", "MATH 324"):
        entry = bulletin.lookup(code, live=True)
        print(f"\nBulletin {code}: {entry.source if entry else 'NOT FOUND'}")
        if entry:
            print(f"  {entry.title} | prereqs: {entry.prerequisites} | codes: {entry.prereq_codes}\n  {entry.description[:200]}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

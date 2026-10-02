"""Text utilities: name normalization, tokenizing and redaction."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

import numpy as np

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the their this to was were
    with we you your can will which when what how why if then than so such these those use used using also
    not no but do does done our out one two may must each per via about over under up down more most""".split()
)


def normalize_name(name: str) -> str:
    """Canonical key for exact concept matching: 'Binary Search Trees (BST)' -> 'binary search tree bst'."""
    words = [_singular(w) for w in _WORD.findall(name.lower())]
    return " ".join(w for w in words if w not in {"the", "a", "an"})


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text: str) -> list[str]:
    return [_singular(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1]


def jaccard(a: str, b: str) -> float:
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def hashed_embedding(text: str, dim: int = 768) -> list[float]:
    """Deterministic bag of unigrams + bigrams (the offline stand-in for semantic embeddings): lexical, but stable."""
    toks = tokens(text)
    vec = np.zeros(dim, dtype=np.float32)
    for f in toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "little")
        vec[h % dim] += 1.0 if (h >> 63) & 1 else -1.0
    norm = float(np.linalg.norm(vec))
    return (vec / norm).tolist() if norm else vec.tolist()


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


class BM25:
    """Okapi BM25 over a small passage set (keyword half of hybrid retrieval)."""

    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokens(d)) for d in docs]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.docs else 0.0
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokens(query)
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in q:
                tf = doc.get(t)
                if tf:
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / (self.avg or 1)))
            out.append(s)
        return out


def rrf(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal rank fusion of several rankings of the same items."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: -kv[1])


def contains_phrase(text: str, phrase: str) -> bool:
    """Whole-word phrase match on normalized tokens ('regression' matches 'Regression models', not 'regressions?')."""
    hay = " " + " ".join(_singular(w) for w in _WORD.findall(text.lower())) + " "
    needle = " " + " ".join(_singular(w) for w in _WORD.findall(phrase.lower())) + " "
    return needle.strip() != "" and needle in hay


def course_code(text: str) -> str:
    """'ds612' / 'DS-612' / 'ds 612' -> 'DS 612'."""
    match = re.search(r"\b([A-Za-z]{2,5})\s*-?\s*(\d{3}[A-Za-z]?)\b", text or "")
    return f"{match.group(1).upper()} {match.group(2).upper()}" if match else (text or "").strip().upper()
# Syllabi carry instructor contact details. Strip them before text is stored or sent to an AI model.

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?:\(\d{3}\)\s*|\b\d{3}[-.\s])\d{3}[-.\s]\d{4}\b")
_URL_WITH_ID = re.compile(r"https?://\S*(?:instructure\.com|zoom\.us|discord\.(?:gg|com))\S*", re.IGNORECASE)
_TITLED_NAME = re.compile(r"\b(Dr|Prof|Professor|Mr|Ms|Mrs|Mx)\.?\s+[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?")
_ROLE_LINE = re.compile(r"^(\s*(?:Instructor|Professor|Teacher|Lecturer|TA|Teaching Assistant)s?\s*[:\-]\s*)(.+)$", re.IGNORECASE | re.MULTILINE)


def redact(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _PHONE.sub("[phone]", text)
    text = _URL_WITH_ID.sub("[link]", text)
    text = _TITLED_NAME.sub(lambda m: f"{m.group(1)}. [name]", text)
    return _ROLE_LINE.sub(lambda m: m.group(1) + _strip_name(m.group(2)), text)


def _strip_name(rest: str) -> str:
    # Keep anything after the name on the same line (e.g. "Email: ..." already redacted), drop the name itself.
    parts = re.split(r"(\s{2,}|\t|\s+(?=Email|Office|Phone)\b)", rest, maxsplit=1)
    tail = "".join(parts[1:]) if len(parts) > 1 else ""
    return "[name]" + tail

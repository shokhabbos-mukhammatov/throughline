"""The prerequisite graph: entity resolution over concept names, and a cycle-safe concept DAG.

Several independent mapping runs (and different batches of the syllabus) name the same idea differently:
"Least Squares Regression", "Simple Linear Regression", "Linear Regression Basics". Resolution runs in
three tiers, cheapest first:
  1. exact match on normalized names and on the hand-written library's aliases;
  2. embedding similarity: pairs above `merge` are merged outright;
  3. pairs in the ambiguous band [ask, merge) go to the model as a same/different judgment.
Union-find turns accepted pairs into clusters. Edges ("A builds on B") are then added strongest-first
and skipped if they would close a cycle, so the result is always a DAG; a transitive reduction keeps
only direct relations for display and scheduling.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .llm import Engine, PairCard
from .seed import library
from .textutil import hashed_embedding, normalize_name

log = logging.getLogger(__name__)

PAIRS_PER_CALL = 40


@dataclass(frozen=True)
class Thresholds:
    merge: float
    ask: float


# Calibrated per embedding space: semantic (Gemini) vs lexical hashing (offline).
ONLINE = Thresholds(merge=0.93, ask=0.82)
OFFLINE = Thresholds(merge=0.90, ask=0.55)


class UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        self.parent[max(ra, rb)] = min(ra, rb)
        return True


@dataclass
class Cluster:
    id: int
    names: Counter = field(default_factory=Counter)
    summaries: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        # Most frequently proposed spelling; ties go to the shorter, then alphabetical.
        return sorted(self.names.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0][0]

    @property
    def aliases(self) -> list[str]:
        return sorted(n for n in self.names if normalize_name(n) != normalize_name(self.name))

    @property
    def summary(self) -> str:
        return max(self.summaries, key=len) if self.summaries else ""


@dataclass
class Resolution:
    clusters: list[Cluster]
    of: dict[str, int]  # normalized name -> cluster id
    stats: dict[str, int]

    def cluster_of(self, name: str) -> Cluster:
        return self.clusters[self.of[normalize_name(name)]]


def resolve(engine: Engine, names: list[tuple[str, str]]) -> Resolution:
    """Cluster (name, summary) proposals into canonical concepts."""
    keys: list[str] = []
    first: dict[str, int] = {}
    texts: list[str] = []
    counts: Counter = Counter()
    summaries: dict[str, list[str]] = {}
    spellings: dict[str, Counter] = {}
    for name, summary in names:
        key = normalize_name(name)
        if not key:
            continue
        counts[key] += 1
        spellings.setdefault(key, Counter())[name.strip()] += 1
        if summary:
            summaries.setdefault(key, []).append(summary.strip())
        if key not in first:
            first[key] = len(keys)
            keys.append(key)
            texts.append(f"{name}: {summary}")
    n = len(keys)
    uf = UnionFind(n)
    stats = {"names": n, "exact_library": 0, "embedding": 0, "asked": 0, "judged_same": 0}

    # Tier 1: the hand-written library knows some aliases.
    lib_of = {i: library.find(keys[i]) for i in range(n)}
    by_lib: dict[str, int] = {}
    for i, lib in lib_of.items():
        if lib is None:
            continue
        if lib.key in by_lib:
            stats["exact_library"] += uf.union(by_lib[lib.key], i)
        else:
            by_lib[lib.key] = i

    # Tier 2: embeddings.
    thresholds = ONLINE if engine.online else OFFLINE
    try:
        vectors = engine.embed(texts) if n > 1 else []
    except Exception as exc:  # embedding outage: fall back to lexical vectors and stricter thresholds
        log.warning("embedding failed, using lexical fallback: %s", exc)
        vectors, thresholds = [hashed_embedding(t) for t in texts], OFFLINE
    ambiguous: list[tuple[int, int, float]] = []
    if n > 1:
        m = np.asarray(vectors, dtype=np.float32)
        m /= np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)
        sims = m @ m.T
        for i in range(n):
            for j in range(i + 1, n):
                s = float(sims[i, j])
                if s >= thresholds.merge:
                    stats["embedding"] += uf.union(i, j)
                elif s >= thresholds.ask and uf.find(i) != uf.find(j):
                    ambiguous.append((i, j, s))

    # Tier 3: ask the model about the ambiguous band, most similar first.
    ambiguous.sort(key=lambda t: -t[2])
    ambiguous = ambiguous[: PAIRS_PER_CALL * 3]
    for start in range(0, len(ambiguous), PAIRS_PER_CALL):
        batch = ambiguous[start : start + PAIRS_PER_CALL]
        shown = lambda i: spellings[keys[i]].most_common(1)[0][0]  # the model sees real names, not normalized keys
        cards = [PairCard(f"p{start + k}", shown(i), (summaries.get(keys[i]) or [""])[0], shown(j), (summaries.get(keys[j]) or [""])[0])
                 for k, (i, j, _) in enumerate(batch)]
        stats["asked"] += len(cards)
        try:
            verdicts = {j.pair_id: j.same for j in engine.judge_same(cards).judgments}
        except Exception as exc:
            log.warning("judge_same failed: %s", exc)
            continue
        for k, (i, j, _) in enumerate(batch):
            if verdicts.get(f"p{start + k}"):
                stats["judged_same"] += uf.union(i, j)

    roots: dict[int, int] = {}
    clusters: list[Cluster] = []
    of: dict[str, int] = {}
    for i, key in enumerate(keys):
        r = uf.find(i)
        if r not in roots:
            roots[r] = len(clusters)
            clusters.append(Cluster(id=len(clusters)))
        c = clusters[roots[r]]
        c.names.update(spellings[key])
        c.summaries.extend(summaries.get(key, []))
        of[key] = c.id
    stats["clusters"] = len(clusters)
    return Resolution(clusters=clusters, of=of, stats=stats)
def _reachable(adj: dict[int, set[int]], start: int, target: int) -> bool:
    stack, seen = [start], {start}
    while stack:
        x = stack.pop()
        if x == target:
            return True
        for y in adj.get(x, ()):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return False


def acyclic_edges(candidates: list[tuple[int, int, float]]) -> tuple[list[tuple[int, int, float]], int]:
    """Greedily keep the strongest edges (src before dst) that don't close a cycle. Returns (kept, dropped)."""
    adj: dict[int, set[int]] = {}
    kept, dropped = [], 0
    for src, dst, weight in sorted(candidates, key=lambda e: -e[2]):
        if src == dst or dst in adj.get(src, set()):
            continue
        if _reachable(adj, dst, src):  # dst already leads to src: adding src->dst makes a cycle
            dropped += 1
            continue
        adj.setdefault(src, set()).add(dst)
        kept.append((src, dst, weight))
    return kept, dropped


def transitive_reduction(edges: list[tuple[int, int, float]]) -> list[tuple[int, int, float]]:
    """Drop src->dst when another path src->...->dst exists (keeps only direct relations)."""
    adj: dict[int, set[int]] = {}
    for s, d, _ in edges:
        adj.setdefault(s, set()).add(d)
    out = []
    for s, d, w in edges:
        adj[s].discard(d)
        if not _reachable(adj, s, d):
            out.append((s, d, w))
        adj[s].add(d)
    return out


def topological_order(nodes: list[str], edges: list[tuple[str, str]]) -> list[str]:
    """Kahn's algorithm; ties broken by the input order so results are stable."""
    indeg = {n: 0 for n in nodes}
    out: dict[str, list[str]] = {n: [] for n in nodes}
    for s, d in edges:
        if s in indeg and d in indeg:
            out[s].append(d)
            indeg[d] += 1
    order_index = {n: i for i, n in enumerate(nodes)}
    ready = sorted((n for n in nodes if indeg[n] == 0), key=order_index.get)
    result = []
    while ready:
        n = ready.pop(0)
        result.append(n)
        for d in out[n]:
            indeg[d] -= 1
            if indeg[d] == 0:
                ready.append(d)
                ready.sort(key=order_index.get)
    return result + [n for n in nodes if n not in result]  # only reachable if the input had a cycle


def depths(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path depth from any source (foundations are 0)."""
    depth = {n: 0 for n in nodes}
    for n in topological_order(nodes, edges):
        for s, d in edges:
            if s == n and d in depth:
                depth[d] = max(depth[d], depth[n] + 1)
    return depth

"""What a student knows, as a probability over knowledge states on the course's prerequisite graph.

This follows Knowledge Space Theory (the approach behind ALEKS): if Multiple Regression builds on Simple
Regression, nobody "knows" the first without the second, so the only feasible knowledge states are the
downsets of the graph. We keep a probability distribution over those states:

  prior      each concept's prior from what the student told us ("studied it" / "not sure" / "never")
             and whether a listed prerequisite covers it, multiplied out over feasible states only;
  evidence   each multiple-choice answer has a slip (know it, answer wrong: 10%) and a guess (don't know it,
             answer right: 25% with four options) probability, and updates every state;
  marginal   P(knows concept) = total probability of the states that contain it.

So a correct answer on a dependent concept raises its foundations, and a wrong one on a foundation lowers
what builds on it. One correct answer alone (prior 50%) gives 78%: below Ready (85%). Two give 93%.
When the graph is too large to enumerate (more than 2^16 states) we fall back to independent concepts.

The adaptive check asks the question with the largest expected information gain about the concepts the
student needs soon, and stops when no question would teach us much.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .models import Concept, Edge, Enrollment, Response

Status = Literal["ready", "likely", "refresh", "learn", "unchecked"]

LABEL: dict[str, str] = {
    "ready": "Ready",
    "likely": "Probably known",
    "refresh": "Refresh",
    "learn": "Learn",
    "unchecked": "Not checked yet",
}

SLIP, GUESS = 0.10, 0.25
READY, LIKELY = 0.85, 0.60
MAX_STATES = 1 << 16
MIN_GAIN = 0.02  # bits; below this a question isn't worth the student's time
PRIOR_BY_REPORT = {"yes": 0.60, "unsure": 0.40, "never": 0.08}


def _h(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return -(p * np.log2(p) + (1 - p) * np.log2(1 - p))


def coverage_applies(concept: Concept, enrollment: Enrollment) -> bool:
    """Evidence that a listed prerequisite teaches it only counts if that is the prerequisite this student took
    (a course can list alternatives: "DS 110 or MATH 108 or MATH 110")."""
    return not (enrollment.prereq_taken and concept.covered_by and concept.covered_by != enrollment.prereq_taken)


def prior_for(concept: Concept, enrollment: Enrollment, in_notes: bool = False) -> float:
    report = enrollment.self_report.get(concept.id)
    if report in PRIOR_BY_REPORT:
        return PRIOR_BY_REPORT[report]
    if in_notes:
        return 0.60  # the student's own notes from an earlier course cover it: they were taught it
    if concept.coverage == "listed" and enrollment.route == "took_here" and coverage_applies(concept, enrollment):
        return 0.55
    if concept.coverage == "missing" or (enrollment.route in ("equivalent", "permission") and concept.coverage != "listed"):
        return 0.35
    return 0.50


@dataclass
class KnowledgeModel:
    ids: list[str]
    parents: list[list[int]]
    children: list[list[int]]
    prior: np.ndarray
    states: np.ndarray | None  # bitmasks of feasible states (exact mode)
    bits: np.ndarray | None  # states x concepts, bool
    log_post: np.ndarray | None
    p_indep: np.ndarray | None  # fallback mode: independent marginals
    responses: dict[int, list[bool]] = field(default_factory=dict)

    @property
    def exact(self) -> bool:
        return self.states is not None
    @classmethod
    def build(cls, concepts: list[Concept], edges: list[Edge], enrollment: Enrollment, responses: list[Response],
              in_notes: frozenset[str] | set[str] = frozenset()) -> "KnowledgeModel":
        ids = [c.id for c in concepts]
        index = {cid: i for i, cid in enumerate(ids)}
        n = len(ids)
        parents: list[list[int]] = [[] for _ in range(n)]
        children: list[list[int]] = [[] for _ in range(n)]
        for e in edges:
            if e.src in index and e.dst in index and e.src != e.dst:
                parents[index[e.dst]].append(index[e.src])
                children[index[e.src]].append(index[e.dst])
        order = _topo(n, parents)
        prior = np.asarray([prior_for(c, enrollment, c.id in in_notes) for c in concepts], dtype=np.float64)

        states = _downsets(order, parents) if n <= 30 else None
        model = cls(ids=ids, parents=parents, children=children, prior=prior, states=None, bits=None, log_post=None, p_indep=None)
        if states is not None:
            arr = np.asarray(states, dtype=np.int64)
            bits = ((arr[:, None] >> np.arange(n, dtype=np.int64)) & 1).astype(bool)
            logp = np.where(bits, np.log(prior), np.log1p(-prior)).sum(axis=1)
            model.states, model.bits, model.log_post = arr, bits, logp - logp.max()
        else:
            model.p_indep = prior.copy()
        for r in sorted(responses, key=lambda r: r.at):
            if r.concept_id in index:
                model.observe(index[r.concept_id], r.correct)
        return model
    def _likelihood(self, i: int, correct: bool) -> np.ndarray:
        known = self.bits[:, i]  # type: ignore[index]
        if correct:
            return np.where(known, 1 - SLIP, GUESS)
        return np.where(known, SLIP, 1 - GUESS)

    def observe(self, i: int, correct: bool) -> None:
        self.responses.setdefault(i, []).append(correct)
        if self.exact:
            self.log_post = self.log_post + np.log(self._likelihood(i, correct))  # type: ignore[operator]
            self.log_post -= self.log_post.max()
        else:
            p = self.p_indep[i]  # type: ignore[index]
            lk = (1 - SLIP, GUESS) if correct else (SLIP, 1 - GUESS)
            self.p_indep[i] = p * lk[0] / (p * lk[0] + (1 - p) * lk[1])  # type: ignore[index]

    def _posterior(self) -> np.ndarray:
        w = np.exp(self.log_post)  # type: ignore[arg-type]
        return w / w.sum()

    def marginals(self) -> np.ndarray:
        if not self.exact:
            return self.p_indep.copy()  # type: ignore[union-attr]
        return self._posterior() @ self.bits  # type: ignore[operator]

    def related(self, i: int) -> set[int]:
        """Ancestors and descendants of i: the concepts whose answers say something about it."""
        out: set[int] = set()
        for nbrs in (self.parents, self.children):
            stack = list(nbrs[i])
            while stack:
                x = stack.pop()
                if x not in out:
                    out.add(x)
                    stack.extend(nbrs[x])
        return out

    def expected_gain(self, i: int, focus: list[int]) -> float:
        """Expected reduction in uncertainty (bits) about the `focus` concepts from asking about concept i."""
        if not focus:
            return 0.0
        if not self.exact:
            p = self.p_indep[i]  # type: ignore[index]
            if i not in focus:
                return 0.0
            pc = p * (1 - SLIP) + (1 - p) * GUESS
            post_c = p * (1 - SLIP) / pc
            post_w = p * SLIP / (1 - pc)
            return float(_h(np.array([p]))[0] - (pc * _h(np.array([post_c]))[0] + (1 - pc) * _h(np.array([post_w]))[0]))
        post = self._posterior()
        f = self.bits[:, focus]  # type: ignore[index]
        before = _h(post @ f).sum()
        lc = self._likelihood(i, True)
        pc = float(post @ lc)
        after = 0.0
        for lk, prob in ((lc, pc), (1 - lc, 1 - pc)):
            if prob <= 1e-12:
                continue
            q = post * lk
            q /= q.sum()
            after += prob * _h(q @ f).sum()
        return float(before - after)


def _topo(n: int, parents: list[list[int]]) -> list[int]:
    indeg = [len(p) for p in parents]
    children: list[list[int]] = [[] for _ in range(n)]
    for d, ps in enumerate(parents):
        for s in ps:
            children[s].append(d)
    ready = [i for i in range(n) if indeg[i] == 0]
    order = []
    while ready:
        x = ready.pop(0)
        order.append(x)
        for c in children[x]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
    return order + [i for i in range(n) if i not in order]


def _downsets(order: list[int], parents: list[list[int]]) -> list[int] | None:
    """All prerequisite-closed sets, built in topological order. None if there are too many to enumerate."""
    states = [0]
    for i in order:
        need = 0
        for p in parents[i]:
            need |= 1 << p
        added = [s | (1 << i) for s in states if s & need == need]
        states.extend(added)
        if len(states) > MAX_STATES:
            return None
    return states


@dataclass
class ConceptState:
    status: Status
    p: float
    correct: int
    attempts: int
    basis: str  # plain-language explanation of where the estimate comes from


def assess(model: KnowledgeModel, concepts: list[Concept], enrollment: Enrollment, names: dict[str, str],
           notes: dict[str, str] | None = None) -> dict[str, ConceptState]:
    notes = notes or {}  # concept id -> where the student's own notes cover it, e.g. "MATH 108 slides"
    p_all = model.marginals()
    out: dict[str, ConceptState] = {}
    for i, c in enumerate(concepts):
        p = float(p_all[i])
        own = model.responses.get(i, [])
        rel = [j for j in model.related(i) if model.responses.get(j)]
        report = enrollment.self_report.get(c.id)
        if own:
            basis = f"{sum(own)} of {len(own)} of your answers on it were right"
            if rel:
                basis += f", plus your answers on {', '.join(names[model.ids[j]] for j in rel[:2])}"
        elif rel:
            basis = "Inferred from your answers on " + ", ".join(names[model.ids[j]] for j in rel[:3])
        elif report:
            basis = {"yes": "You said you've studied it", "unsure": "You weren't sure you'd studied it",
                     "never": "You said you've never studied it"}[report]
        elif c.id in notes:
            basis = f"Your {notes[c.id]} cover it; no answers yet"
        else:
            basis = "No answers yet"

        if p >= READY and (own or rel):
            status: Status = "ready"
        elif report == "never" and p < LIKELY:
            status = "learn"
        elif not own and not rel:
            status = "unchecked"
        elif p >= LIKELY:
            status = "likely"
        elif report == "unsure" and not any(own):
            status = "learn"
        else:
            status = "refresh"
        out[c.id] = ConceptState(status=status, p=round(p, 3), correct=sum(own), attempts=len(own), basis=basis)
    return out

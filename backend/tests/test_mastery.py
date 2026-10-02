"""The knowledge-space student model: feasible states, Bayesian updates, statuses, information gain."""

from datetime import datetime, timedelta, timezone

import pytest

from throughline import mastery as mx
from throughline.models import Concept, Edge, Enrollment, Response

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def chain(*names):
    """Concepts a -> b -> c (each builds on the previous)."""
    cs = [Concept(id=n, name=n) for n in names]
    es = [Edge(src=a.id, dst=b.id) for a, b in zip(cs, cs[1:])]
    return cs, es


def resp(cid, ok, i):
    return Response(student="s", question_id=f"q{i}", concept_id=cid, choice=0, correct=ok, at=T0 + timedelta(minutes=i))


def test_states_are_the_downsets_of_the_graph():
    cs, es = chain("a", "b", "c")
    m = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [])
    # a chain of 3 has exactly 4 prerequisite-closed states: {}, {a}, {a,b}, {a,b,c}
    assert m.exact and sorted(m.states.tolist()) == [0b000, 0b001, 0b011, 0b111]
    two = [Concept(id=x, name=x) for x in "xy"]
    assert len(mx.KnowledgeModel.build(two, [], Enrollment(id="s"), []).states) == 4  # independent: all subsets


def test_one_lucky_guess_is_not_ready_two_are():
    c = [Concept(id="a", name="a")]
    one = mx.KnowledgeModel.build(c, [], Enrollment(id="s"), [resp("a", True, 0)])
    assert one.marginals()[0] == pytest.approx(0.5 * 0.9 / (0.5 * 0.9 + 0.5 * 0.25))  # 0.78
    assert mx.assess(one, c, Enrollment(id="s"), {"a": "a"})["a"].status == "likely"
    two = mx.KnowledgeModel.build(c, [], Enrollment(id="s"), [resp("a", True, 0), resp("a", True, 1)])
    assert mx.assess(two, c, Enrollment(id="s"), {"a": "a"})["a"].status == "ready"


def test_evidence_flows_along_the_graph():
    cs, es = chain("a", "b", "c")
    base = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), []).marginals()
    up = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [resp("c", True, 0)]).marginals()
    assert up[0] > base[0] and up[1] > base[1], "knowing c implies knowing its foundations"
    down = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [resp("a", False, 0), resp("a", False, 1)]).marginals()
    assert down[2] < base[2], "missing a foundation lowers what builds on it"
    states = mx.assess(mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [resp("c", True, 0), resp("c", True, 1)]),
                       cs, Enrollment(id="s"), {c.id: c.name for c in cs})
    assert states["a"].attempts == 0 and "Inferred" in states["a"].basis


def test_self_report_and_statuses():
    c = [Concept(id="a", name="a")]
    never = Enrollment(id="s", self_report={"a": "never"})
    assert mx.assess(mx.KnowledgeModel.build(c, [], never, []), c, never, {"a": "a"})["a"].status == "learn"
    yes = Enrollment(id="s", self_report={"a": "yes"})
    assert mx.assess(mx.KnowledgeModel.build(c, [], yes, []), c, yes, {"a": "a"})["a"].status == "unchecked"
    wrong = mx.KnowledgeModel.build(c, [], yes, [resp("a", False, 0)])
    assert mx.assess(wrong, c, yes, {"a": "a"})["a"].status == "refresh"
    unsure = Enrollment(id="s", self_report={"a": "unsure"})
    assert mx.assess(mx.KnowledgeModel.build(c, [], unsure, [resp("a", False, 0)]), c, unsure, {"a": "a"})["a"].status == "learn"


def test_information_gain_prefers_the_informative_question():
    cs, es = chain("a", "b", "c")
    m = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [])
    focus = [0, 1, 2]
    gains = [m.expected_gain(i, focus) for i in range(3)]
    assert all(g > 0 for g in gains)
    # Once a concept is pinned down, asking about it again teaches little.
    pinned = mx.KnowledgeModel.build(cs, es, Enrollment(id="s"), [resp("b", True, i) for i in range(4)])
    assert pinned.expected_gain(1, focus) < m.expected_gain(1, focus)


def test_large_graphs_fall_back_to_independent_concepts():
    cs = [Concept(id=f"c{i}", name=f"c{i}") for i in range(40)]
    m = mx.KnowledgeModel.build(cs, [], Enrollment(id="s"), [resp("c0", True, 0)])
    assert not m.exact and m.marginals()[0] > 0.7

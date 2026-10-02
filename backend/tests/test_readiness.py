from datetime import date, timedelta

from throughline.assessment import adaptive_next, answer
from throughline.models import Enrollment
from throughline.readiness import Snapshot, plan, timeline
from throughline.seed import sample


def setup(ctx, student="stu", **enroll):
    course = sample.create_sample(ctx, "owner", simulate=False)
    repo = ctx.course(course.id)
    repo.enrollments.put(Enrollment(id=student, **enroll))
    return course, repo, Snapshot.load(course, repo, student, ctx.now().date())


def by_name(repo, name):
    return next(c for c in repo.concepts.list() if c.name == name)


def test_sample_places_today_in_week_four(ctx):
    course, _, snap = setup(ctx)
    assert snap.week_now == 4
    tl = timeline(snap)
    assert [t["week"] for t in tl] == list(range(1, 15))
    assert all(t["past"] for t in tl if t["week"] < 4)


def test_plan_schedules_before_the_class_that_needs_it(ctx):
    _, _, snap = setup(ctx, weekly_minutes=600)
    p = plan(snap)
    assert p["week_now"] == 4 and p["counts"]["to_do"] > 0
    for wk in p["weeks"]:
        for item in wk["items"]:
            assert date.fromisoformat(wk["start"]) <= date.fromisoformat(item["do_by"]) <= date.fromisoformat(item["due"])


def test_foundations_come_first_with_adjusted_deadlines(ctx):
    course, repo, _ = setup(ctx)
    mlr, slr = by_name(repo, "Multiple Linear Regression"), by_name(repo, "Simple Linear Regression")
    desc = by_name(repo, "Descriptive Statistics")
    snap = Snapshot.load(course, repo, "stu2", ctx.now().date())
    repo.enrollments.put(Enrollment(id="stu2", weekly_minutes=240, self_report={mlr.id: "never", slr.id: "never", desc.id: "never"}))
    snap = Snapshot.load(course, repo, "stu2", ctx.now().date())
    p = plan(snap)
    order = [i["name"] for wk in p["weeks"] for i in wk["items"]] + [r["name"] for r in p["at_risk"]]
    assert order.index("Descriptive Statistics") < order.index("Simple Linear Regression") < order.index("Multiple Linear Regression")
    items = {i["name"]: i for wk in p["weeks"] for i in wk["items"]} | {r["name"]: r for r in p["at_risk"]}
    assert items["Simple Linear Regression"]["do_by"] <= items["Multiple Linear Regression"]["do_by"]
    # Descriptive statistics is used directly only in week 11, but regression builds on it now.
    desc_item = items["Descriptive Statistics"]
    assert desc_item["do_by"] < desc_item["due"] and desc_item["before"] == "Simple Linear Regression"


def test_never_studied_takes_hours_and_can_be_at_risk(ctx):
    course, repo, _ = setup(ctx)
    everything = {c.id: "never" for c in repo.concepts.list()}
    repo.enrollments.put(Enrollment(id="stu3", weekly_minutes=60, self_report=everything))
    p = plan(Snapshot.load(course, repo, "stu3", ctx.now().date()))
    chain_rule = by_name(repo, "Derivatives and the Chain Rule")
    risky = {r["concept_id"]: r for r in p["at_risk"]}
    assert p["counts"]["learn"] == len(everything)
    assert chain_rule.id in risky and risky[chain_rule.id]["short_by"] > 0


def test_adaptive_check_targets_foundations_and_stops(ctx):
    _, repo, snap = setup(ctx)
    asked, session = [], []
    for _ in range(12):
        nxt = adaptive_next(snap, repo, session)
        if nxt["done"]:
            break
        q = nxt["question"]
        key = repo.questions.get(q["id"]).correct_index
        wrong = q["concept_name"] == "Multiple Linear Regression"
        res = answer(snap, repo, q["id"], (key + 1) % 4 if wrong else key, "check")
        session.append(res["response_id"])
        asked.append((q["concept_name"], nxt["reason"]))
    assert nxt["done"] and 1 <= len(asked) <= 8
    assert "correct_index" not in nxt.get("question", {})
    names = [a for a, _ in asked]
    assert names[0] == "Simple Linear Regression", "the foundation shared by the next weeks is the most informative first question"


def test_answer_reports_inferences(ctx):
    _, repo, snap = setup(ctx)
    mlr = by_name(repo, "Multiple Linear Regression")
    q = next(x for x in repo.questions.list(concept_id=mlr.id))
    res = answer(snap, repo, q.id, q.correct_index, "check")
    assert res["correct"] is True and res["p_after"] > res["p_before"]
    assert any(ch["name"] == "Simple Linear Regression" for ch in res["also_changed"]), "a right answer raises its foundation"


def test_term_without_dates_uses_week_numbers(ctx):
    course, repo, _ = setup(ctx)
    course.term_start = None
    snap = Snapshot.load(course, repo, "stu", ctx.now().date())
    assert snap.week_now == 1
    dates = [t["date"] for t in timeline(snap)]
    assert dates == sorted(dates) and date.fromisoformat(dates[1]) - date.fromisoformat(dates[0]) == timedelta(weeks=1)

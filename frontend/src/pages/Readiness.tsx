import { useQuery } from "@tanstack/react-query";
import { Icon, Spinner, StatusIcon } from "../components/ui";
import { api, type CourseDetail, type PlanItem, type StudySource } from "../lib/api";
import { dueLabel, minutes, shortDate } from "../lib/format";

const SOURCE_TAG: Record<StudySource["kind"], string> = { notes: "Your notes", syllabus: "Syllabus", open_textbook: "Free", web: "Free" };

/** Where to study it: the student's own notes (with the slide or page) first, then free textbook sections. */
export function WhereToLearn({ sources, quotes = false }: { sources: StudySource[]; quotes?: boolean }) {
  if (!sources.length) return null;
  return (
    <ul className="where">
      {sources.map((s, i) => (
        <li key={i}>
          <span className={`src-tag ${s.kind}`}>{SOURCE_TAG[s.kind]}</span>
          <span>
            {s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : <b>{s.title}</b>}
            {s.detail && <span className="muted"> · {s.detail}</span>}
            {quotes && s.quote && <q className="small">{s.quote}</q>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Item({ courseId, it }: { courseId: string; it: PlanItem }) {
  // do_by is earlier than due when something later in the graph is waiting on this concept.
  const early = !it.overdue && it.do_by < it.due;
  // Not checked yet: the item is a guess, so it stays a single quiet line until the check gives it a status.
  const compact = it.status === "unchecked";
  return (
    <div className={`plan-item st-${it.status}${compact ? " compact" : ""}`}>
      <span className={`status ${it.status}`}><StatusIcon status={it.status} /></span>
      <span className="pi-main">
        <a className="pi-name" href={`#/c/${courseId}/k/${it.concept_id}`}><b>{it.name}</b></a>
        <span className="pi-why">
          {it.status_label}
          {!compact && it.partial ? ` · part of ${minutes(it.total_minutes)}` : ""}
          {!compact && (it.foundation_for ? <> · foundation for <b>{it.foundation_for}</b></> : it.before && early ? <> · comes before <b>{it.before}</b></> : null)}
          {" "}· week {it.for_week}{compact ? "" : `: ${it.for_title}`}
          {!compact && it.coverage === "missing" ? " · not in listed prerequisites" : ""}
        </span>
        {(!compact || it.study?.[0]?.kind === "notes") && <WhereToLearn sources={(it.study ?? []).slice(0, 1)} />}
      </span>
      <span className="pi-right">
        <span className="mono">{minutes(it.minutes)}</span>
        {early ? (
          <span className="small muted" title={`The course needs it ${shortDate(it.due)}, but ${it.before ?? it.foundation_for ?? "what builds on it"} builds on it and is needed sooner.`}>
            Finish by {shortDate(it.do_by)}
          </span>
        ) : (
          <span className={`small ${it.overdue ? "late" : "muted"}`}>{dueLabel(it.due, it.overdue)}</span>
        )}
      </span>
    </div>
  );
}

export function PlanTab({ course, onCheck }: { course: CourseDetail; onCheck: () => void }) {
  const { data: plan, isLoading } = useQuery({ queryKey: ["plan", course.id], queryFn: () => api.plan(course.id) });
  if (isLoading || !plan) return <section className="sheet"><div className="empty"><Spinner /></div></section>;
  const c = plan.counts;
  const checkFirst = c.unchecked > 0 && c.unchecked * 2 >= c.to_do;

  return (
    <div className="plan-layout">
      <section className="sheet taped">
        <div className="sheet-head">
          <h2>Your pace plan</h2>
          <span className="muted small">{minutes(plan.weekly_minutes)} a week · <a href={`#/c/${course.id}/setup`}>change setup</a></span>
        </div>
        <div className="sheet-body">
          {checkFirst && (
            <div className="check-first sticky">
              <h3>Start with a <span className="nowrap">3-minute</span> check</h3>
              <button className="btn primary" onClick={onCheck}><Icon name="check" /> Take the quick check</button>
              <p>
                {c.unchecked} of the {c.to_do} concepts below are guesses until you answer a few questions (up to 8). Each answer also
                tells us about the concepts around it, so the plan sharpens fast.
              </p>
            </div>
          )}
          <div className="stat-row">
            <div><span className="stat">{c.to_do}</span><span className="label">to do</span></div>
            <div><span className="stat">{minutes(plan.total_minutes)}</span><span className="label">total</span></div>
            {c.learn > 0 && <div><span className="stat">{c.learn}</span><span className="label">to learn</span></div>}
            {c.refresh > 0 && <div><span className="stat">{c.refresh}</span><span className="label">to refresh</span></div>}
            {c.ready > 0 && <div><span className="stat">{c.ready}</span><span className="label">ready</span></div>}
          </div>
          {!checkFirst && c.unchecked + c.likely > 0 && (
            <p className="notice">
              {c.unchecked > 0 && <>{c.unchecked} concept{c.unchecked === 1 ? "" : "s"} not checked yet. </>}
              {c.likely > 0 && <>{c.likely} probably known but not confirmed. </>}
              A few questions turn guesses into a real plan; each answer also tells us about the concepts it builds on.{" "}
              <button className="btn primary small" onClick={onCheck}>Take the quick check</button>
            </p>
          )}
          {c.foundations > 0 && (
            <p className="small muted">
              {c.foundations} item{c.foundations === 1 ? " is a foundation" : "s are foundations"}: not used directly in class yet, but something you need to learn builds on {c.foundations === 1 ? "it" : "them"},
              so {c.foundations === 1 ? "it's" : "they're"} scheduled first.
            </p>
          )}
          {plan.at_risk.length > 0 && (
            <div className="risk">
              <h3><Icon name="warn" /> Won't fit before it's needed</h3>
              <p className="small">At {minutes(plan.weekly_minutes)} a week, these can't be finished in time. Start today, raise your weekly time, or get help: the Tutoring and Academic Support Center (Library 220) and your instructor's office hours exist for exactly this.</p>
              <ul className="plain">
                {plan.at_risk.map((r) => (
                  <li key={r.concept_id}><a href={`#/c/${course.id}/k/${r.concept_id}`}><b>{r.name}</b></a> · needed {shortDate(r.due)} for week {r.for_week} · short by {minutes(r.short_by ?? 0)}</li>
                ))}
              </ul>
            </div>
          )}
          {!plan.weeks.length && !plan.at_risk.length && (
            <div className="empty"><b>You're on pace.</b><span>Everything the coming weeks need is marked ready.</span></div>
          )}
          {plan.weeks.map((w) => (
            <div key={w.start} className="plan-week">
              <h3>
                <span>{w.start <= plan.today && plan.today <= w.end ? "This week" : `Week of ${shortDate(w.start)}`}</span>
                <span>{minutes(w.minutes)} of {minutes(w.capacity)}</span>
              </h3>
              {w.items.map((it) => <Item key={it.concept_id + w.start} courseId={course.id} it={it} />)}
            </div>
          ))}
        </div>
      </section>
      <aside className="sheet side pinned">
        <div className="sheet-head"><h3>Coming up</h3></div>
        <div className="sheet-body">
          {(course.timeline ?? []).filter((t) => !t.past).slice(0, 4).map((t) => (
            <div key={t.id} className="upcoming">
              <span className="label">{t.kind === "assessment" ? "Assessment" : `Week ${t.week}`} · {shortDate(t.date)}{t.estimated ? " (est.)" : ""}</span>
              <b>{t.title}</b>
              {t.requires.length ? (
                <ul className="mini">
                  {t.requires.map((r) => (
                    <li key={r.concept_id}><span className={`status ${r.status}`}><StatusIcon status={r.status} size={12} /></span> <a href={`#/c/${course.id}/k/${r.concept_id}`}>{r.name}</a></li>
                  ))}
                </ul>
              ) : <span className="small muted">No earlier-course prerequisites found.</span>}
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

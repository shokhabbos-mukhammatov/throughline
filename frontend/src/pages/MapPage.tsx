import { StatusIcon } from "../components/ui";
import type { CourseDetail } from "../lib/api";
import { TIMELINE_LABEL, shortDate } from "../lib/format";

/** The course week by week, with the earlier-course knowledge each item relies on. */
export function TimelineTab({ course }: { course: CourseDetail }) {
  const items = course.timeline ?? [];
  const week = course.week_now ?? 1;
  return (
    <section className="sheet taped">
      <div className="sheet-head">
        <h2>Timeline</h2>
        <span className="muted small">{TIMELINE_LABEL[course.timeline_kind].hint}</span>
      </div>
      <ol className="timeline">
        {items.map((t) => (
          <li key={t.id} className={`tl ${t.past ? "past" : ""} ${t.week === week ? "now" : ""}`}>
            <div className="tl-when">
              <span className="mono">{t.kind === "assessment" ? "QUIZ/EXAM" : `WEEK ${t.week}`}</span>
              <span className="small muted">{shortDate(t.date)}{t.estimated ? " (est.)" : ""}</span>
              {t.week === week && <span className="today-flag">NOW</span>}
            </div>
            <div className="tl-body">
              <b>{t.title}</b>
              {t.details && <p className="small ink2">{t.details}</p>}
              {t.requires.length > 0 && (
                <ul className="req-chips">
                  {t.requires.map((r) => (
                    <li key={r.concept_id}>
                      <a className={`req st-${r.status}`} href={`#/c/${course.id}/k/${r.concept_id}`} title={r.how_used}>
                        <span className={`status ${r.status}`}><StatusIcon status={r.status} size={12} /></span>
                        {r.name}
                        {r.importance === "helpful" && <span className="muted"> · helpful</span>}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

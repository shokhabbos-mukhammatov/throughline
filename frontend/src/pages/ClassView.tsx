import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CoverageTag, Icon, Spinner } from "../components/ui";
import { api, type ClassRow, type CourseDetail } from "../lib/api";
import { pct, shortDate } from "../lib/format";

type Metric = "first_try" | "never" | "ready";
const METRICS: { id: Metric; label: string; hint: string; good: "high" | "low" }[] = [
  { id: "first_try", label: "Right on the first try", hint: "Share of students whose first answer was correct", good: "high" },
  { id: "never", label: "Never studied it", hint: "Share of students who said they never studied it", good: "low" },
  { id: "ready", label: "Ready now", hint: "Share of students whose last two answers were correct", good: "high" },
];

function band(v: number | null, good: "high" | "low"): string {
  if (v == null) return "none";
  const score = good === "high" ? v : 1 - v;
  return score >= 0.8 ? "b4" : score >= 0.6 ? "b3" : score >= 0.4 ? "b2" : "b1";
}

function concernText(r: ClassRow): string {
  const parts = [];
  if (r.never != null && r.never >= 0.25) parts.push(`${pct(r.never)} say they never studied it`);
  if (r.first_try != null && r.first_try < 0.6) parts.push(`${pct(r.first_try)} got it right on the first try`);
  return parts.join(", and ");
}

export function ClassViewTab({ course }: { course: CourseDetail }) {
  const [sim, setSim] = useState(true);
  const [metric, setMetric] = useState<Metric>("first_try");
  const { data, isLoading } = useQuery({
    queryKey: ["class", course.id, sim],
    queryFn: () => api.classView(course.id, sim),
    refetchInterval: 4000, // live during a demo or a class session
  });
  if (isLoading || !data) return <section className="sheet"><div className="empty"><Spinner /></div></section>;
  const m = METRICS.find((x) => x.id === metric)!;
  const weeks = data.weeks;

  return (
    <div className="class-layout">
      <section className="sheet taped">
        <div className="sheet-head">
          <h2>Class view</h2>
          <span className="muted small">{data.students} student{data.students === 1 ? "" : "s"}{data.simulated ? `, including ${data.simulated} simulated` : ""} · updates live</span>
        </div>
        <div className="sheet-body">
          {data.simulated > 0 && (
            <p className="notice warn">
              Includes {data.simulated} <b>simulated</b> students so this view isn't empty in a demo.{" "}
              <label className="inline"><input type="checkbox" checked={sim} onChange={(e) => setSim(e.target.checked)} /> Show simulated students</label>
            </p>
          )}
          <p className="small muted"><Icon name="lock" /> No names, ever. A concept's numbers appear only once at least {data.min_cell} students have answered, so no one's result can be singled out.</p>
          <div className="seg" role="radiogroup" aria-label="Metric" style={{ margin: "12px 0" }}>
            {METRICS.map((x) => (
              <button key={x.id} className={metric === x.id ? "on" : ""} aria-pressed={metric === x.id} title={x.hint} onClick={() => setMetric(x.id)}>{x.label}</button>
            ))}
          </div>
          <div className="heat-wrap">
            <table className="heat">
              <thead>
                <tr>
                  <th scope="col" className="heat-name">Prerequisite</th>
                  {weeks.map((w) => <th key={w} scope="col" className={`wk ${w === data.week_now ? "now" : ""}`}>{w}</th>)}
                  <th scope="col" className="num n">n</th>
                  <th scope="col" className="num"><span className="long">{m.label}</span><span className="short">%</span></th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => {
                  const v = r[metric];
                  const b = r.suppressed ? "suppressed" : band(v, m.good);
                  return (
                    <tr key={r.concept_id}>
                      <th scope="row" className="heat-name">
                        {r.name}
                        <CoverageTag coverage={r.coverage} covered_by={r.covered_by} />
                      </th>
                      {weeks.map((w) => (
                        <td key={w} className={`wk ${w === data.week_now ? "now" : ""}`}>
                          {r.weeks.includes(w) && <span className={`cell ${b}`} title={r.suppressed ? `Fewer than ${data.min_cell} students` : `${m.label}: ${pct(v)}`} />}
                        </td>
                      ))}
                      <td className="num mono n">{r.n}</td>
                      <td className="num mono">{r.suppressed ? <span className="muted" title={`Hidden until ${data.min_cell} students answer`}>&lt;{data.min_cell}</span> : pct(v)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="legend">
            <span className="item"><span className="cell b1" /> weakest</span>
            <span className="item"><span className="cell b2" /></span>
            <span className="item"><span className="cell b3" /></span>
            <span className="item"><span className="cell b4" /> strongest</span>
            <span className="item"><span className="cell suppressed" /> fewer than {data.min_cell} students</span>
          </div>
        </div>
      </section>
      <aside className="sheet side pinned">
        <div className="sheet-head"><h3>Worth class time soon</h3></div>
        <div className="sheet-body">
          {data.concerns.length === 0 ? (
            <p className="muted small">No weak spots in the next three weeks yet.</p>
          ) : (
            <ul className="concerns">
              {data.concerns.map((r) => (
                <li key={r.concept_id}>
                  <b>{r.name}</b>
                  <span className="small">Needed for week {r.first_week} ({shortDate(r.first_date)}): {r.first_title}. {concernText(r)}.</span>
                  {r.coverage === "missing" && <span className="small muted">No listed prerequisite teaches it.</span>}
                </li>
              ))}
            </ul>
          )}
          <p className="small muted" style={{ marginTop: 12 }}>Ideas: a five-minute warm-up before that week, a pointer to the free section in the plan, or a TASC drop-in session.</p>
        </div>
      </aside>
    </div>
  );
}

import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { CoverageTag, Spinner } from "../components/ui";
import { api, type CourseDetail, type Route, type SelfReport } from "../lib/api";
import { ROUTE_LABEL, shortDate } from "../lib/format";

const TIMES = [60, 120, 180, 300, 480];

export function Setup({ course, onDone }: { course: CourseDetail; onDone: (check: boolean) => void }) {
  const qc = useQueryClient();
  const [route, setRoute] = useState<Route>(course.enrollment?.route ?? "unsure");
  const alternatives = course.official_prereqs;
  const [taken, setTaken] = useState<string>(course.enrollment?.prereq_taken ?? (alternatives.length === 1 ? alternatives[0] : ""));
  const [weekly, setWeekly] = useState(course.enrollment?.weekly_minutes ?? 180);
  const [reports, setReports] = useState<Record<string, SelfReport>>(course.enrollment?.self_report ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [showAll, setShowAll] = useState(false);
  const all = useMemo(
    () => (course.concepts ?? []).filter((c) => c.next_need && !c.foundation).sort((a, b) => (a.next_need!.date < b.next_need!.date ? -1 : 1)),
    [course.concepts],
  );
  const soon = useMemo(() => {
    const now = course.week_now ?? 1;
    return all.filter((c) => c.next_need!.overdue || c.next_need!.week < Math.max(now, 1) + 3);
  }, [all, course.week_now]);
  const concepts = showAll || soon.length === 0 ? all : soon;
  const prereqName = alternatives.join(" or ") || "the listed prerequisite";

  function pickRoute(r: Route) {
    setRoute(r);
    // Taking the listed course here makes "yes" the likely answer for what that course teaches.
    if (r === "took_here") {
      setReports((prev) => {
        const next = { ...prev };
        for (const c of concepts) if (c.covered_by && (!taken || c.covered_by === taken) && !next[c.id]) next[c.id] = "yes";
        return next;
      });
    }
  }

  async function save(check: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.updateMe(course.id, { route, prereq_taken: route === "took_here" ? taken : "", weekly_minutes: weekly, self_report: reports });
      await qc.invalidateQueries({ queryKey: ["course", course.id] });
      await qc.invalidateQueries({ queryKey: ["plan", course.id] });
      onDone(check);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const answered = concepts.filter((c) => reports[c.id]).length;
  return (
    <section className="sheet setup taped">
      <div className="sheet-head">
        <h2>Set up your pace plan</h2>
        <span className="muted small">About a minute. Only you see your answers; your instructor sees class totals at most.</span>
      </div>
      <div className="sheet-body setup-grid">
        <fieldset>
          <legend className="field-label">1 · How did you meet the prerequisite ({prereqName})?</legend>
          {(Object.keys(ROUTE_LABEL) as Route[]).map((r) => (
            <label key={r} className="radio">
              <input type="radio" name="route" checked={route === r} onChange={() => pickRoute(r)} />{" "}
              {r === "took_here" && alternatives.length > 1 ? "I took one of the listed prerequisites at SF State" : ROUTE_LABEL[r]}
            </label>
          ))}
          {route === "took_here" && alternatives.length > 1 && (
            <div className="field">
              <span className="small">Which one? What it taught decides what you're likely to know.</span>
              <div className="seg small" role="radiogroup" aria-label="Which prerequisite did you take?">
                {alternatives.map((code) => (
                  <button key={code} className={taken === code ? "on" : ""} aria-pressed={taken === code} onClick={() => setTaken(code)}>{code}</button>
                ))}
              </div>
            </div>
          )}
          <p className="small muted">Have notes or slides from that course? Add them under <b>My notes</b> after setup, and your plan points to the exact page or slide.</p>
          {(route === "equivalent" || route === "permission") && (
            <p className="small notice">Equivalent courses and waivers often skip topics this course assumes. Answer honestly below; "never studied" gets you a real study plan, not a quiz.</p>
          )}
        </fieldset>
        <fieldset>
          <legend className="field-label">2 · Time you can spend on prerequisite review each week</legend>
          <div className="seg">
            {TIMES.map((m) => (
              <button key={m} className={weekly === m ? "on" : ""} aria-pressed={weekly === m} onClick={() => setWeekly(m)}>{m / 60} h</button>
            ))}
          </div>
          <p className="small muted">On top of regular coursework. The plan fits into this and tells you when it can't.</p>
        </fieldset>
        <fieldset className="span2">
          <legend className="field-label">3 · Have you studied these before? ({answered} of {concepts.length}{concepts === soon && all.length > soon.length ? ", next 3 weeks" : ""})</legend>
          <ul className="report-list">
            {concepts.map((c) => (
              <li key={c.id}>
                <div>
                  <b>{c.name}</b> <CoverageTag coverage={c.coverage} covered_by={c.covered_by} />
                  <div className="small muted">Needed {c.next_need!.overdue ? "already" : `by ${shortDate(c.next_need!.date)}`} · Week {c.next_need!.week}: {c.next_need!.title}</div>
                </div>
                <div className="seg small" role="radiogroup" aria-label={`Studied ${c.name} before?`}>
                  {([["yes", "Yes"], ["unsure", "Not sure"], ["never", "Never"]] as [SelfReport, string][]).map(([v, label]) => (
                    <button key={v} className={reports[c.id] === v ? "on" : ""} aria-pressed={reports[c.id] === v}
                            onClick={() => setReports((p) => ({ ...p, [c.id]: v }))}>{label}</button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          {all.length > soon.length && soon.length > 0 && (
            <button className="btn ghost small" style={{ alignSelf: "flex-start" }} onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Only the next 3 weeks" : `Show all ${all.length} (optional)`}
            </button>
          )}
        </fieldset>
      </div>
      <div className="sheet-foot">
        <button className="btn primary" disabled={busy} onClick={() => save(true)}>{busy ? <Spinner /> : null} Save and take the quick check</button>
        <button className="btn" disabled={busy} onClick={() => save(false)}>Save and see my plan</button>
        {error && <span className="error-text">{error}</span>}
        {course.enrolled && <span className="spacer" />}
        {course.enrolled && (
          <button className="btn ghost small danger" disabled={busy} onClick={async () => {
            if (!window.confirm(`Delete your answers and setup for ${course.code}? This can't be undone.`)) return;
            setBusy(true);
            try {
              await api.deleteMe(course.id);
              setReports({});
              await qc.invalidateQueries({ queryKey: ["course", course.id] });
              qc.removeQueries({ queryKey: ["plan", course.id] });
              qc.removeQueries({ queryKey: ["graph", course.id] });
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}>Delete my data for this course</button>
        )}
      </div>
    </section>
  );
}

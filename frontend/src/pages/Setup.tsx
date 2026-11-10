import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { PrereqQuestions, PriorCourseList, named, openChoices, orList, type MetMap } from "../components/Background";
import { CoverageTag, Spinner } from "../components/ui";
import { api, type CourseDetail, type PriorCourseDraft, type SelfReport } from "../lib/api";
import { shortDate } from "../lib/format";

const TIMES = [60, 120, 180, 300, 480];

export function Setup({ course, onDone }: { course: CourseDetail; onDone: (check: boolean) => void }) {
  const qc = useQueryClient();
  const groups = course.prereq_groups;
  const titles = useMemo(() => Object.fromEntries(course.bulletin.map((b) => [b.code, b.title])), [course.bulletin]);
  const [met, setMet] = useState<MetMap>(course.enrollment?.met ?? {});
  const [drafts, setDrafts] = useState<PriorCourseDraft[]>([]);
  const [adding, setAdding] = useState<string | null>(null);
  const [draftErrors, setDraftErrors] = useState<Record<string, string>>({});
  const { data: saved } = useQuery({ queryKey: ["background", course.id], queryFn: () => api.background(course.id) });
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
  const open = openChoices(groups, met);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["course", course.id] });
    qc.invalidateQueries({ queryKey: ["background", course.id] });
    qc.invalidateQueries({ queryKey: ["plan", course.id] });
    qc.invalidateQueries({ queryKey: ["graph", course.id] });
  }

  // Answers are saved as they change, so the "taught in" labels below follow the courses you actually took.
  function changeMet(next: MetMap) {
    setMet(next);
    api.updateMe(course.id, { met: next, draft: !course.enrolled }).then(refresh).catch(() => undefined);
  }

  async function addCourse(d: PriorCourseDraft) {
    setAdding(d.uid);
    setDraftErrors((m) => ({ ...m, [d.uid]: "" }));
    try {
      await api.addPriorCourse(course.id, d);
      setDrafts((ds) => ds.filter((x) => x.uid !== d.uid));
      refresh();
    } catch (e) {
      setDraftErrors((m) => ({ ...m, [d.uid]: (e as Error).message }));
    } finally {
      setAdding(null);
    }
  }

  async function save(check: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.updateMe(course.id, { met, weekly_minutes: weekly, self_report: reports });
      for (const d of drafts.filter(named)) {  // typed in but not added yet
        await api.addPriorCourse(course.id, d);
        setDrafts((ds) => ds.filter((x) => x.uid !== d.uid));
      }
      await qc.invalidateQueries({ queryKey: ["course", course.id] });
      await qc.invalidateQueries({ queryKey: ["plan", course.id] });
      qc.invalidateQueries({ queryKey: ["background", course.id] });
      qc.invalidateQueries({ queryKey: ["graph", course.id] });
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
        <div className="span2 setup-step">
          <span className="field-label">1 · {groups.length ? "The prerequisites, and how you met each one" : "Courses you took before"}</span>
          {groups.length > 1 && <span className="small muted">This course asks for {groups.length} things. Answer each one separately.</span>}
          <PrereqQuestions groups={groups} titles={titles} met={met} onMet={changeMet} drafts={drafts} onDrafts={setDrafts}
                           saved={saved ?? []} onAdd={addCourse} adding={adding} errors={draftErrors} />
          {saved && saved.length > 0 && (
            <>
              <span className="label">Courses you've added · only you can see these</span>
              <PriorCourseList items={saved} courseId={course.id} total={(course.concepts ?? []).length}
                               onRemove={async (id) => { await api.deletePriorCourse(course.id, id); refresh(); }} />
            </>
          )}
          <p className="small muted">Kept your notes or slides too? Add them under <b>My notes</b> after setup, and your plan points to the exact page or slide.</p>
        </div>
        <fieldset className="span2">
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
        <button className="btn primary" disabled={busy || open.length > 0} onClick={() => save(true)}>{busy ? <Spinner /> : null} Save and take the quick check</button>
        <button className="btn" disabled={busy || open.length > 0} onClick={() => save(false)}>Save and see my plan</button>
        {open.length > 0 && <span className="small notice warn">First say which of {open.map(orList).join("; and which of ")} you took (step 1).</span>}
        {error && <span className="error-text">{error}</span>}
        {course.enrolled && <span className="spacer" />}
        {course.enrolled && (
          <button className="btn ghost small danger" disabled={busy} onClick={async () => {
            if (!window.confirm(`Delete your answers, earlier courses and setup for ${course.code}? This can't be undone.`)) return;
            setBusy(true);
            try {
              await api.deleteMe(course.id);
              setReports({});
              setMet({});
              await qc.invalidateQueries({ queryKey: ["course", course.id] });
              qc.invalidateQueries({ queryKey: ["background", course.id] });
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

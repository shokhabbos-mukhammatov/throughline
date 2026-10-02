import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useDialog } from "../lib/useDialog";
import { api, type CourseDetail, type SelfReport } from "../lib/api";
import { minutes, shortDate } from "../lib/format";
import { WhereToLearn } from "../pages/Readiness";
import { CheckCard } from "./CheckCard";
import { CoverageTag, Icon, Markdown, ProbBar, ResourceList, Spinner, StatusChip } from "./ui";

/** Study one concept: why the course needs it, the refresher or a learn path, free resources, practice. */
export function ConceptDrawer({ course, conceptId, onClose }: { course: CourseDetail; conceptId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: s, refetch } = useQuery({ queryKey: ["study", course.id, conceptId], queryFn: () => api.study(course.id, conceptId) });
  const [round, setRound] = useState(0);
  const [answered, setAnswered] = useState(false);

  const dialog = useDialog<HTMLElement>(onClose);

  function refreshAll() {
    qc.invalidateQueries({ queryKey: ["course", course.id] });
    qc.invalidateQueries({ queryKey: ["plan", course.id] });
  }

  async function report(v: SelfReport) {
    await api.updateMe(course.id, { self_report: { [conceptId]: v } });
    await refetch();
    refreshAll();
  }

  const learning = s?.status === "learn";
  return (
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label={s?.name ?? "Concept"}>
        <button className="btn ghost close" onClick={onClose} aria-label="Close"><Icon name="close" /></button>
        {!s ? (
          <div className="empty"><Spinner /></div>
        ) : (
          <>
            <div className="drawer-head">
              <h2>{s.name}</h2>
              <div className="meta">
                <span>Prerequisite for {course.code}</span>
                <StatusChip status={s.status} />
                <CoverageTag coverage={s.coverage} covered_by={s.covered_by} />
                {s.foundation && <span className="tag">Foundation</span>}
              </div>
              <div className="estimate">
                <ProbBar p={s.p} />
                <span className="small muted">{s.basis}</span>
              </div>
              <p className="ink2">{s.summary}</p>
              {s.depth && <p className="small"><b>Depth this course needs:</b> {s.depth}</p>}
              {(s.builds_on.length > 0 || s.leads_to.length > 0) && (
                <p className="small">
                  {s.builds_on.length > 0 && <>Builds on <b>{s.builds_on.join(", ")}</b>. </>}
                  {s.leads_to.length > 0 && <>Needed for <b>{s.leads_to.join(", ")}</b>.</>}
                </p>
              )}
            </div>
            <div className="drawer-body">
              <section>
                <span className="label">Where {course.code} uses it</span>
                <ul className="uses">
                  {s.uses.map((u, i) => (
                    <li key={i} className={u.past ? "past" : ""}>
                      <span className="mono small">{u.kind === "assessment" ? "Quiz/exam" : `Wk ${u.week}`} · {shortDate(u.date)}</span>
                      <span><b>{u.title}.</b> {u.how_used} {u.importance === "helpful" && <span className="muted small">(helpful, not essential)</span>}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section>
                <span className="label">Is it taught in a prerequisite?</span>
                {s.evidence_items.length > 0 ? (
                  <ul className="evidence">
                    {s.evidence_items.map((e, i) => (
                      <li key={i} className={`ev-${e.verdict}`}>
                        <span className="small muted">{e.source}</span>
                        <q>{e.quote}</q>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="small muted">{s.evidence || "No evidence either way yet."}</p>
                )}
              </section>

              <section>
                <div className="meta" style={{ justifyContent: "space-between" }}>
                  <span className="label">{learning ? `Learn it · about ${minutes(s.learn_minutes)}` : `Refresher · about ${minutes(s.refresh_minutes)}`}</span>
                  <span className="seg small" role="radiogroup" aria-label="Have you studied this before?">
                    {([["yes", "Studied it"], ["never", "Never studied"]] as [SelfReport, string][]).map(([v, label]) => (
                      <button key={v} className={s.self_report === v ? "on" : ""} aria-pressed={s.self_report === v} onClick={() => report(v)}>{label}</button>
                    ))}
                  </span>
                </div>
                {learning ? (
                  <>
                    <p className="small">You haven't studied this yet, so plan real study time. A quick refresher won't be enough, and that's normal for prerequisites taken elsewhere or waived.</p>
                    <Markdown text={s.learn_outline || "Start with the resources below, then come back for practice."} />
                  </>
                ) : (
                  <Markdown text={s.refresher || s.summary} />
                )}
              </section>

              <section>
                <span className="label">Where to learn it</span>
                {s.where_to_learn.length ? <WhereToLearn sources={s.where_to_learn} quotes /> : <ResourceList resources={s.resources} />}
                {!s.in_your_notes.length && (
                  <p className="small muted">Have notes or slides from an earlier course? <a href={`#/c/${course.id}/notes`} onClick={onClose}>Add them</a> and this shows the exact page.</p>
                )}
              </section>

              <section>
                <span className="label">Practice</span>
                {s.practice ? (
                  <>
                    <CheckCard key={`${s.practice.id}-${round}`} courseId={course.id} question={{ ...s.practice, concept_name: s.name }} phase="practice"
                               label={s.status === "likely" ? "One more to confirm" : "Practice"}
                               onResult={() => { setAnswered(true); refreshAll(); }} />
                    {answered && (
                      <button className="btn" style={{ marginTop: 10 }} onClick={async () => { setAnswered(false); await refetch(); setRound((r) => r + 1); }}>
                        Next question <Icon name="arrow" />
                      </button>
                    )}
                  </>
                ) : (
                  <p className="muted small">No approved questions for this concept yet.</p>
                )}
              </section>
            </div>
          </>
        )}
      </aside>
    </>
  );
}

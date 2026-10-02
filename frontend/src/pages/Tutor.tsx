import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { CheckCard } from "../components/CheckCard";
import { Icon, ProbBar, Spinner, StatusChip } from "../components/ui";
import { useDialog } from "../lib/useDialog";
import { api, type AnswerResult, type CheckStep, type CourseDetail } from "../lib/api";

/**
 * The adaptive quick check. The server picks each next question by expected information gain on the
 * prerequisite graph, says why it picked it, and ends the check once another question wouldn't tell us much.
 */
export function CheckSession({ course, onClose }: { course: CourseDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [session, setSession] = useState<string[]>([]);
  const [step, setStep] = useState<CheckStep | null>(null);
  const [answered, setAnswered] = useState<AnswerResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [right, setRight] = useState(0);

  const load = useCallback(async (ids: string[]) => {
    setError(null);
    setAnswered(null);
    setStep(null); // drop the answered card so it can't be read or clicked as the next question
    try {
      setStep(await api.checkNext(course.id, ids));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [course.id]);

  useEffect(() => { load([]); }, [load]);

  const finish = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["course", course.id] });
    qc.invalidateQueries({ queryKey: ["plan", course.id] });
    qc.invalidateQueries({ queryKey: ["graph", course.id] });
    onClose();
  }, [qc, course.id, onClose]);

  const dialog = useDialog<HTMLDivElement>(finish);

  const q = step && !step.done ? step.question : null;
  return (
    <>
      <div className="scrim" onClick={finish} />
      <div className="modal" ref={dialog} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Quick check">
        <div className="modal-head">
          <h2>Quick check</h2>
          {step && !step.done && <span className="label check-count">Question {session.length + 1} · up to {step.max_questions}</span>}
          <button className="btn ghost close" onClick={finish} aria-label="Close"><Icon name="close" /></button>
        </div>
        <div className="modal-body">
          {!step && !error && <div className="empty"><Spinner /></div>}
          {error && <p className="error-text">{error}</p>}
          {q && step && (
            <>
              <p className="why"><Icon name="arrow" size={13} /> {step.reason}</p>
              <CheckCard key={q.id} courseId={course.id} question={q} phase="check" onResult={(r) => {
                setAnswered(r);
                if (r.correct) setRight((n) => n + 1);
              }} />
              <div className="row-actions" style={{ marginTop: 14, justifyContent: "flex-end" }}>
                <button className="btn" disabled={!answered} onClick={() => {
                  const ids = answered ? [...session, answered.response_id] : session;
                  setSession(ids);
                  load(ids);
                }}>
                  Next <Icon name="arrow" />
                </button>
              </div>
            </>
          )}
          {step?.done && (
            <div className="results">
              {session.length === 0 ? (
                <p><b>Nothing to check right now.</b> What the next weeks need is either already clear from your answers, or marked "never studied", which goes straight to a study plan.</p>
              ) : (
                <p>
                  {right} of {session.length} right. That was enough to place you on {step.focus.length} concepts: each answer also tells us
                  about the concepts it builds on or leads to, so you don't get asked about everything.
                </p>
              )}
              <ul className="plain result-list">
                {step.focus.map((c) => (
                  <li key={c.id}>
                    <a href={`#/c/${course.id}/k/${c.id}`} onClick={finish}>{c.name}</a>
                    <span className="result-right"><ProbBar p={c.p} /><StatusChip status={c.status} /></span>
                  </li>
                ))}
              </ul>
              <div className="row-actions"><button className="btn primary" onClick={finish}>See my updated plan</button></div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

import { useState } from "react";
import { api, type AnswerResult, type Question } from "../lib/api";
import { pct } from "../lib/format";
import { Markdown, ProbBar, StatusChip } from "./ui";

const LETTERS = "ABCD";

/** One multiple-choice question. Grading happens on the server; the key arrives only with the result. */
export function CheckCard({
  courseId,
  question,
  phase,
  label,
  onResult,
}: {
  courseId: string;
  question: Question;
  phase: "check" | "practice";
  label?: string;
  onResult?: (r: AnswerResult) => void;
}) {
  const [choice, setChoice] = useState<number | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const done = result != null;

  async function submit() {
    if (choice == null) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.answer(courseId, question.id, choice, phase);
      setResult(r);
      onResult?.(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="check" aria-label={`Question about ${question.concept_name ?? "a prerequisite"}`}>
      <div className="check-head">
        <span className="label">{label ?? (phase === "check" ? "Quick check" : "Practice")}{question.concept_name ? ` · ${question.concept_name}` : ""}</span>
      </div>
      <div className="check-prompt">
        <Markdown text={question.prompt} />
      </div>
      <div className="choices" role="radiogroup">
        {question.choices.map((c, i) => (
          <button
            key={i}
            className={`choice ${done && i === result.correct_index ? "correct" : ""} ${done && i === choice && i !== result.correct_index ? "wrong" : ""}`}
            aria-pressed={choice === i}
            disabled={done || busy}
            onClick={() => setChoice(i)}
          >
            <span className="letter">{LETTERS[i]}</span>
            <Markdown text={c} />
          </button>
        ))}
      </div>
      {!done && (
        <div className="row-actions" style={{ marginTop: 10 }}>
          <button className="btn primary small" disabled={busy || choice == null} onClick={submit}>
            {busy ? "Checking…" : "Check my answer"}
          </button>
          <button className="btn ghost small" disabled={busy} onClick={() => { setChoice(null); }} hidden={choice == null}>
            Clear
          </button>
          {error && <span className="error-text">{error}</span>}
        </div>
      )}
      {done && (
        <div className="verdict" aria-live="polite">
          <div className="meta" style={{ justifyContent: "space-between" }}>
            <strong style={{ color: result.correct ? "var(--good-ink)" : "var(--critical-ink)" }}>{result.correct ? "Correct" : "Not quite"}</strong>
            <StatusChip status={result.status_after} />
          </div>
          <Markdown text={result.explanation} />
          <div className="estimate">
            <span className="label">Chance you know {question.concept_name ?? "it"}: {pct(result.p_before)} → {pct(result.p_after)}</span>
            <ProbBar p={result.p_after} label={false} />
          </div>
          {result.also_changed.length > 0 && (
            <p className="small muted inference">
              Because these build on each other, this answer also moved:{" "}
              {result.also_changed.map((c, i) => (
                <span key={c.concept_id}>{i ? "; " : ""}<b>{c.name}</b> {pct(c.p_before)} → {pct(c.p_after)}</span>
              ))}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

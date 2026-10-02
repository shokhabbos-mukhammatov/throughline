import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CoverageTag, FileDrop, Markdown, ResourceList, Spinner } from "../components/ui";
import { api, type CourseDetail, type ReviewQuestion, type StageTrace } from "../lib/api";
import { pct } from "../lib/format";

const LETTERS = "ABCD";

function QuestionRow({ courseId, q }: { courseId: string; q: ReviewQuestion }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  async function set(status: ReviewQuestion["status"]) {
    setBusy(true);
    await api.patchQuestion(courseId, q.id, { status });
    await qc.invalidateQueries({ queryKey: ["review", courseId] });
    setBusy(false);
  }
  return (
    <li className={`rq ${q.status}`}>
      <div className="rq-head">
        <span className={`pill ${q.verification === "disagreed" ? "warn" : q.verification === "agreed" ? "ok" : ""}`}
              title={q.verification === "disagreed" ? q.verification_note : undefined}>
          {q.verification === "agreed" ? "Answer key double-checked" : q.verification === "disagreed" ? "Answer key disputed" : q.origin === "sample" ? "Hand-written" : "Not double-checked"}
        </span>
        <span className="pill">{q.status === "approved" ? "Shown to students" : q.status === "draft" ? "Hidden until approved" : "Rejected"}</span>
      </div>
      <Markdown text={q.prompt} />
      <ol className="rq-choices">
        {q.choices.map((c, i) => (
          <li key={i} className={i === q.correct_index ? "key" : ""}><span className="letter">{LETTERS[i]}</span> <Markdown text={c} /></li>
        ))}
      </ol>
      {q.verification === "disagreed" && <p className="small error-text">{q.verification_note}</p>}
      <div className="row-actions">
        {q.status !== "approved" && <button className="btn small" disabled={busy} onClick={() => set("approved")}>Approve</button>}
        {q.status !== "rejected" && <button className="btn small danger" disabled={busy} onClick={() => set("rejected")}>Reject</button>}
      </div>
    </li>
  );
}

function Trace({ trace }: { trace: StageTrace[] }) {
  if (!trace.length) return null;
  const total = trace.reduce((n, t) => n + Object.values(t.calls).reduce((a, b) => a + b, 0), 0);
  return (
    <details className="trace-box" open>
      <summary><b>How this map was built</b> <span className="muted small">{trace.length} stages · {total} engine calls · {(trace.reduce((n, t) => n + t.ms, 0) / 1000).toFixed(1)} s</span></summary>
      <table className="trace">
        <thead><tr><th>Stage</th><th className="num">Time</th><th>Engine calls</th><th>What happened</th></tr></thead>
        <tbody>
          {trace.map((t, i) => (
            <tr key={i}>
              <td>{t.stage}</td>
              <td className="num mono">{t.ms >= 1000 ? `${(t.ms / 1000).toFixed(1)} s` : `${t.ms} ms`}</td>
              <td className="mono small">{Object.entries(t.calls).map(([k, v]) => `${k} ×${v}`).join(", ") || "none (code only)"}</td>
              <td className="small">{t.notes.join(" · ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function PrereqUpload({ course }: { course: CourseDetail }) {
  const qc = useQueryClient();
  const [code, setCode] = useState(course.official_prereqs[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  return (
    <div className="prereq-upload">
      <span className="label">Check coverage against what the prerequisite actually taught</span>
      <p className="small muted">
        Bulletin descriptions are a sentence or two. Upload the prerequisite course's syllabus and every "not confirmed" concept gets a real answer,
        with the line that shows it. {course.prereq_docs.length > 0 && <>Already added: {course.prereq_docs.join(", ")}.</>}
      </p>
      <FileDrop compact file={file} onFile={setFile} accept=".pdf,.docx,.txt,.md,.html,image/*" label="Prerequisite syllabus"
                prompt="Drop the prerequisite's syllabus here" />
      <div className="form-row">
        <input type="text" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. DS 212" aria-label="Prerequisite course" style={{ width: 130 }} />
        <button className="btn small" disabled={busy || !code.trim()} onClick={async () => {
          const f = file;
          if (!f) return setMsg("Choose the syllabus file first.");
          setBusy(true);
          setMsg(null);
          try {
            await api.addPrereqSyllabus(course.id, code, f);
            setMsg("Added. Re-checking coverage…");
            setFile(null);
            setTimeout(() => {
              qc.invalidateQueries({ queryKey: ["review", course.id] });
              qc.invalidateQueries({ queryKey: ["course", course.id] });
            }, 1500);
          } catch (e) {
            setMsg((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}>{busy ? <Spinner /> : null} Add and re-check</button>
      </div>
      {msg && <p className="small">{msg}</p>}
    </div>
  );
}

/** For whoever added the course: check the AI's map, its evidence and its questions before relying on them. */
export function ReviewTab({ course }: { course: CourseDetail }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["review", course.id], queryFn: () => api.review(course.id) });
  if (isLoading || !data) return <section className="sheet"><div className="empty"><Spinner /></div></section>;
  const counts = data.concepts.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.coverage]: (acc[c.coverage] ?? 0) + 1 }), {});

  return (
    <section className="sheet taped">
      <div className="sheet-head">
        <h2>Review the map</h2>
        <span className="muted small">
          {data.concepts.length} concepts ({data.concepts.filter((c) => c.foundation).length} foundations) · {data.edges.length} prerequisite relations ·{" "}
          {data.flagged} question{data.flagged === 1 ? "" : "s"} with a disputed answer key
        </span>
      </div>
      <div className="sheet-body review">
        <Trace trace={data.trace} />
        <p className="small">
          Coverage: <b>{counts.listed ?? 0}</b> taught in a listed prerequisite (quote found) · <b>{counts.likely ?? 0}</b> probably ·{" "}
          <b>{counts.missing ?? 0}</b> not in listed prerequisites · <b>{counts.unknown ?? 0}</b> not confirmed
        </p>
        <PrereqUpload course={course} />
        {data.edges.length > 0 && (
          <p className="small muted">Relations: {data.edges.map((e) => `${e.src} → ${e.dst}`).join(" · ")}</p>
        )}
        {data.concepts.map((c) => (
          <details key={c.id} className={`rc ${c.removed ? "removed" : ""}`}>
            <summary>
              <b>{c.name}</b> <CoverageTag coverage={c.coverage} covered_by={c.covered_by} />
              {c.foundation && <span className="tag">Foundation</span>}
              {!course.demo && <span className="pill" title="Share of independent mapping runs that proposed it">Agreement {pct(c.confidence)}</span>}
              {c.questions.some((q) => q.verification === "disagreed" && q.status === "draft") && <span className="pill warn">Needs review</span>}
              {c.removed && <span className="pill">Removed</span>}
            </summary>
            <p>{c.summary}</p>
            {c.aliases.length > 0 && <p className="small muted">Also called: {c.aliases.join(", ")}</p>}
            {c.depth && <p className="small"><b>Depth:</b> {c.depth}</p>}
            <p className="small"><b>Evidence:</b> {c.evidence || "none"}</p>
            <ResourceList resources={c.resources} />
            <ul className="plain">{c.questions.map((q) => <QuestionRow key={q.id} courseId={course.id} q={q} />)}</ul>
            <button className="btn small ghost" onClick={async () => {
              await api.patchConcept(course.id, c.id, { removed: !c.removed });
              qc.invalidateQueries({ queryKey: ["review", course.id] });
              qc.invalidateQueries({ queryKey: ["course", course.id] });
            }}>{c.removed ? "Restore this concept" : "Remove this concept from the map"}</button>
          </details>
        ))}
      </div>
    </section>
  );
}

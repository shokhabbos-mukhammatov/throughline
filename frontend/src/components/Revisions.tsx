import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type ChangeKind, type CourseDetail, type MapChangeView, type RevisionView } from "../lib/api";
import { COVERAGE_LABEL, shortDate } from "../lib/format";
import { FileDrop, Icon, Spinner } from "./ui";

const FILE_TYPES = ".pdf,.pptx,.docx,.txt,.md,.html,image/*";
const LETTERS = "ABCD";

const GROUPS: { kinds: ChangeKind[]; title: string }[] = [
  { kinds: ["add_concept"], title: "Add to the map" },
  { kinds: ["remove_concept"], title: "Remove from the map" },
  { kinds: ["edit_concept"], title: "Correct a concept" },
  { kinds: ["add_need", "remove_need"], title: "Change which weeks use it" },
  { kinds: ["add_question"], title: "Questions from your files" },
];

const EXAMPLES = [
  "Week 6 doesn't use logarithms; drop it from that week.",
  "The midterm assumes Bayes' rule. Add it.",
  "Use the attached review guide and sample exam to check the map.",
];

function weekLabel(w: { week: number; title: string } | null) {
  return w ? `Week ${w.week}: ${w.title}` : "";
}

function ChangeRow({ ch, on, toggle, locked }: { ch: MapChangeView; on: boolean; toggle: () => void; locked: boolean }) {
  const [open, setOpen] = useState(false);
  let what: React.ReactNode;
  if (ch.kind === "add_concept") what = <><b>{ch.name}</b> <span className="muted">· needed in {ch.needs.map((n) => `week ${n.week}`).join(", ")}</span></>;
  else if (ch.kind === "remove_concept") what = <><b>{ch.name}</b></>;
  else if (ch.kind === "edit_concept") what = <><b>{ch.current_name}</b>{ch.name !== ch.current_name && <> → <b>{ch.name}</b></>}</>;
  else if (ch.kind === "add_need") what = <><b>{ch.name}</b> <span className="muted">is used in</span> {weekLabel(ch.need)}</>;
  else if (ch.kind === "remove_need") what = <><b>{ch.name}</b> <span className="muted">is not used in</span> {weekLabel(ch.need)}</>;
  else what = <><span className="muted">For</span> <b>{ch.name}</b>: “{ch.questions[0]?.prompt}”</>;
  const details = ch.kind === "add_concept" || ch.kind === "edit_concept" || ch.kind === "add_question";
  return (
    <li className={`rv-change${on ? " on" : ""}`}>
      <label className="rv-pick">
        <input type="checkbox" checked={on} onChange={toggle} disabled={locked} />
        <span className="rv-what">{what}</span>
      </label>
      <div className="rv-why small">
        {ch.reason && <span>{ch.reason}</span>}
        {ch.source && (
          <span className={ch.quote_ok ? "rv-src ok" : "rv-src"}>
            {ch.quote_ok ? <Icon name="check" /> : null} {ch.source}{ch.quote && ch.kind !== "add_question" ? <>: <q>{ch.quote}</q></> : null}
          </span>
        )}
        {!ch.source && ch.kind !== "add_question" && <span className="muted">From your request.</span>}
        {ch.note && <span className="rv-note">{ch.note}</span>}
      </div>
      {details && (
        <button type="button" className="btn ghost small rv-more" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Hide details" : ch.kind === "add_question" ? "Show the question" : "Show details"}
        </button>
      )}
      {open && (
        <div className="rv-detail small">
          {ch.summary && <p>{ch.summary}</p>}
          {ch.depth && <p><b>Depth:</b> {ch.depth}</p>}
          {ch.kind === "add_concept" && (
            <>
              <p><b>Where the course uses it:</b> {ch.needs.map(weekLabel).join(" · ")}</p>
              {ch.builds_on.length > 0 && <p><b>Builds on:</b> {ch.builds_on.join(", ")}</p>}
              {ch.coverage && <p><b>Prerequisites:</b> {COVERAGE_LABEL[ch.coverage].label}{ch.covered_by && (ch.coverage === "listed" || ch.coverage === "likely") ? ` ${ch.covered_by}` : ""}</p>}
            </>
          )}
          {ch.questions.map((q, i) => (
            <div key={i} className="rv-q">
              <p>{q.prompt}</p>
              <ol className="plain">
                {q.choices.map((c, j) => <li key={j} className={j === q.correct_index ? "key" : ""}>{LETTERS[j]}. {c}{j === q.correct_index ? " ✓" : ""}</li>)}
              </ol>
              {q.verification === "disagreed" && <p className="rv-note">An independent solve disagrees with this key. It's added as a draft; approve it in the concept's list below.</p>}
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

function Proposal({ course, rev }: { course: CourseDetail; rev: RevisionView }) {
  const qc = useQueryClient();
  const [chosen, setChosen] = useState<Set<string>>(() => new Set(rev.changes.filter((c) => c.selected).map((c) => c.id)));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const done = rev.status !== "ready";
  const picked = done ? new Set(rev.applied) : chosen;

  function refresh() {
    for (const key of ["revisions", "review", "course", "plan", "graph", "study"]) qc.invalidateQueries({ queryKey: [key, course.id] });
  }

  async function act(apply: boolean) {
    setBusy(true);
    setMsg(null);
    try {
      if (apply) {
        const r = await api.applyRevision(course.id, rev.id, [...chosen]);
        setMsg(`Applied ${r.applied} change${r.applied === 1 ? "" : "s"}. Students' plans use the new map now.` +
          (r.skipped.length ? ` Skipped: ${r.skipped.join("; ")}.` : ""));
      } else {
        await api.discardRevision(course.id, rev.id);
      }
      refresh();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rv-proposal">
      {rev.summary && <p>{rev.summary}</p>}
      {rev.changes.length === 0 && <p className="muted">No changes to propose.</p>}
      {GROUPS.map((g) => {
        const items = rev.changes.filter((c) => g.kinds.includes(c.kind));
        if (!items.length) return null;
        return (
          <section key={g.title} className="rv-group">
            <span className="label">{g.title}</span>
            <ul className="plain">
              {items.map((ch) => (
                <ChangeRow key={ch.id} ch={ch} on={picked.has(ch.id)} locked={done || busy}
                           toggle={() => setChosen((s) => { const n = new Set(s); if (n.has(ch.id)) n.delete(ch.id); else n.add(ch.id); return n; })} />
              ))}
            </ul>
          </section>
        );
      })}
      {rev.not_done.length > 0 && (
        <div className="rv-group">
          <span className="label">Not done</span>
          <ul className="small">{rev.not_done.map((n, i) => <li key={i}>{n}</li>)}</ul>
        </div>
      )}
      {!done && rev.changes.length > 0 && (
        <div className="row-actions">
          <button className="btn primary" disabled={busy || chosen.size === 0} onClick={() => act(true)}>
            {busy ? <Spinner /> : null} Apply {chosen.size} of {rev.changes.length}
          </button>
          <button className="btn ghost" disabled={busy} onClick={() => act(false)}>Discard</button>
          <span className="small muted">Students see the change in their plan as soon as it's applied. Their answers are kept.</span>
        </div>
      )}
      {!done && rev.changes.length === 0 && <button className="btn ghost small" disabled={busy} onClick={() => act(false)}>Close</button>}
      {msg && <p className="small">{msg}</p>}
    </div>
  );
}

const STATUS: Record<RevisionView["status"], string> = {
  queued: "Waiting to start", running: "Working on it", ready: "Ready to review", applied: "Applied", discarded: "Discarded", error: "Failed",
};

/** For the person who added the course: say what the AI got wrong, back it with course files, review, apply. */
export function RevisionPanel({ course }: { course: CourseDetail }) {
  const qc = useQueryClient();
  const { data } = useQuery({
    queryKey: ["revisions", course.id],
    queryFn: () => api.revisions(course.id),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 1500 : false),
  });
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [next, setNext] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const working = data?.find((r) => r.status === "queued" || r.status === "running");
  const latest = data?.[0];
  const earlier = (data ?? []).slice(latest ? 1 : 0);

  useEffect(() => {
    if (next) { setFiles((f) => (f.length < 5 ? [...f, next] : f)); setNext(null); }
  }, [next]);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.askForRevision(course.id, prompt, files);
      setPrompt("");
      setFiles([]);
      qc.invalidateQueries({ queryKey: ["revisions", course.id] });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rv">
      <div className="rv-ask">
        <span className="label">Something wrong in the map? Ask for changes</span>
        <p className="small muted">
          Say what the AI got wrong, and add files from the course that show it: a review guide, a study guide, sample exam or
          quiz questions, slides. You'll see every proposed change, with the line from your file behind it, before anything
          changes for students.
        </p>
        <textarea rows={3} value={prompt} maxLength={4000} onChange={(e) => setPrompt(e.target.value)} aria-label="What should change"
                  placeholder={EXAMPLES.join("\n")} />
        {files.length > 0 && (
          <ul className="plain rv-files">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`}>
                <Icon name="upload" /> {f.name}
                <button type="button" className="btn ghost small" onClick={() => setFiles((fs) => fs.filter((_, j) => j !== i))}>Remove</button>
              </li>
            ))}
          </ul>
        )}
        {files.length < 5 && (
          <FileDrop compact file={next} onFile={setNext} accept={FILE_TYPES} label="Add a course file"
                    prompt={files.length ? "Add another file" : "Drop a review guide, study guide or sample exam here"} />
        )}
        <div className="row-actions">
          <button className="btn primary" disabled={busy || !!working || (prompt.trim().length < 8 && files.length === 0)} onClick={send}>
            {busy ? <><Spinner /> Reading your files…</> : "Propose changes"}
          </button>
          <span className="small muted">Up to 5 files: PDF, PowerPoint, Word, text or a photo. Names, emails and phone numbers are removed.</span>
          {error && <span className="error-text">{error}</span>}
        </div>
      </div>

      {latest && (
        <div className={`rv-item rv-${latest.status}`}>
          <div className="meta" style={{ justifyContent: "space-between" }}>
            <span><b>{STATUS[latest.status]}</b> <span className="muted small">· {shortDate(latest.created_at)}{latest.calls ? ` · ${latest.calls} engine calls` : ""}</span></span>
          </div>
          <p className="small rv-prompt">“{latest.prompt}”{latest.files.length > 0 && <span className="muted"> · {latest.files.map((f) => f.filename).join(", ")}</span>}</p>
          {(latest.status === "queued" || latest.status === "running") && <p className="small"><Spinner /> {latest.stage || "Starting…"}</p>}
          {latest.status === "error" && <p className="error-text small">{latest.error}</p>}
          {(latest.status === "ready" || latest.status === "applied") && <Proposal key={latest.id} course={course} rev={latest} />}
        </div>
      )}
      {earlier.length > 0 && (
        <details className="rv-history">
          <summary className="small">Earlier requests ({earlier.length})</summary>
          <ul className="plain small">
            {earlier.map((r) => (
              <li key={r.id}><b>{STATUS[r.status]}</b> · {shortDate(r.created_at)} · “{r.prompt.slice(0, 140)}”{r.status === "applied" ? ` · ${r.applied.length} changes` : ""}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

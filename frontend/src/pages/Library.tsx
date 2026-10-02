import { useState } from "react";
import { go } from "../App";
import { FileDrop, Spinner } from "../components/ui";
import { api, rememberCourse, type BulletinEntry } from "../lib/api";
import { signInWithGoogle } from "../lib/session";
import { useAccount } from "../lib/useAccount";

/** Add a course: a course number (looked up in the SF State Bulletin) plus its syllabus. */
export function AddCourseForm() {
  const account = useAccount();
  const [code, setCode] = useState("");
  const [entry, setEntry] = useState<BulletinEntry | null>(null);
  const [lookup, setLookup] = useState<"idle" | "busy" | "none">("idle");
  const [file, setFile] = useState<File | null>(null);
  const [paste, setPaste] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [prereqCode, setPrereqCode] = useState("");
  const [prereqFile, setPrereqFile] = useState<File | null>(null);

  async function check() {
    if (code.trim().length < 4) return;
    setLookup("busy");
    try {
      const hit = await api.bulletin(code);
      setEntry(hit);
      setLookup("idle");
      if (!prereqCode && hit.prereq_codes[0]) setPrereqCode(hit.prereq_codes[0]);
    } catch {
      setEntry(null);
      setLookup("none");
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const prereq = prereqFile && prereqCode.trim() ? { code: prereqCode, file: prereqFile } : null;
      const course = await api.addCourse(code, file, paste ? text : "", prereq);
      rememberCourse(course.id);
      go(`/c/${course.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const ready = code.trim().length >= 3 && (paste ? text.trim().length > 80 : file != null) && !(prereqFile && !prereqCode.trim());
  return (
    <div className="add-course">
      <div className="field">
        <label className="field-label" htmlFor="code">Course number</label>
        <input id="code" type="text" placeholder="e.g. DS 612" value={code} autoComplete="off"
               onChange={(e) => { setCode(e.target.value); setEntry(null); setLookup("idle"); }} onBlur={check} />
        {lookup === "busy" && <span className="muted small"><Spinner /> Looking it up in the SF State Bulletin…</span>}
        {entry && (
          <div className="bulletin-hit">
            <b>{entry.code} {entry.title}</b>
            {entry.prerequisites && <span> · Prerequisites: {entry.prerequisites}</span>}
            <span className="muted"> ({entry.source})</span>
          </div>
        )}
        {lookup === "none" && <span className="muted small">Not found in the Bulletin. That's fine; the syllabus is what matters.</span>}
      </div>

      <div className="field">
        <span className="field-label">Syllabus</span>
        {paste ? (
          <textarea rows={6} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the syllabus text, including the schedule." aria-label="Syllabus text" />
        ) : (
          <FileDrop file={file} onFile={setFile} accept=".pdf,.docx,.txt,.md,.html,image/*" label="Syllabus file"
                    prompt={<>Drop the syllabus here (PDF, .docx, text or a photo)</>} />
        )}
        <button className="btn ghost small" style={{ alignSelf: "flex-start" }} onClick={() => setPaste((p) => !p)}>
          {paste ? "Upload a file instead" : "Paste text instead (for example from a Canvas syllabus page)"}
        </button>
      </div>

      <details className="field prereq-optional">
        <summary className="field-label">Optional · the prerequisite course's syllabus</summary>
        <p className="small muted">
          Bulletin descriptions are a sentence or two, so they can't say whether a topic was really covered. With the prerequisite's own
          syllabus, every concept gets a quoted answer: taught there, or not.
        </p>
        <input type="text" value={prereqCode} onChange={(e) => setPrereqCode(e.target.value)} placeholder="Its course number, e.g. DS 212" aria-label="Prerequisite course number" />
        <FileDrop compact file={prereqFile} onFile={setPrereqFile} accept=".pdf,.docx,.txt,.md,.html,image/*" label="Prerequisite syllabus file"
                  prompt="Drop its syllabus here" />
        {prereqFile && !prereqCode.trim() && <span className="error-text small">Add the prerequisite's course number.</span>}
      </details>

      <p className="muted small">
        Instructor names, emails and phone numbers are removed before the syllabus is stored or sent to AI. Syllabi are course materials: don't
        share one outside your class without the instructor's OK.
      </p>
      <div className="row-actions">
        {account.mode === "firebase" && !account.signedIn ? (
          <button className="btn primary" disabled={busy} onClick={() => signInWithGoogle().catch((e) => setError((e as Error).message))}>
            Sign in with Google to map it
          </button>
        ) : (
          <button className="btn primary" disabled={!ready || busy} onClick={submit}>
            {busy ? <Spinner /> : null} Map my course
          </button>
        )}
        {error && <span className="error-text">{error}</span>}
      </div>
    </div>
  );
}

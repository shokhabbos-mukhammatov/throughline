import { useState } from "react";
import { go } from "../App";
import { PrereqQuestions, hasSyllabus, isOwnCopy, named, openChoices, orList, type MetMap } from "../components/Background";
import { FileDrop, Spinner } from "../components/ui";
import { api, rememberCourse, type BulletinEntry, type PriorCourseDraft } from "../lib/api";
import { signInWithGoogle } from "../lib/session";
import { useAccount } from "../lib/useAccount";

/** Add a course: a course number (looked up in the SF State Bulletin), its syllabus, and the prerequisites you took. */
export function AddCourseForm() {
  const account = useAccount();
  const [code, setCode] = useState("");
  const [entry, setEntry] = useState<BulletinEntry | null>(null);
  const [lookup, setLookup] = useState<"idle" | "busy" | "none">("idle");
  const [file, setFile] = useState<File | null>(null);
  const [paste, setPaste] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [met, setMet] = useState<MetMap>({});
  const [drafts, setDrafts] = useState<PriorCourseDraft[]>([]);

  const groups = entry?.prereq_groups ?? [];
  const open = openChoices(groups, met);

  async function check() {
    if (code.trim().length < 4) return;
    setLookup("busy");
    try {
      const hit = await api.bulletin(code);
      setEntry(hit);
      setLookup("idle");
    } catch {
      setEntry(null);
      setLookup("none");
    }
  }

  async function submit() {
    setError(null);
    // A listed prerequisite's own syllabus is evidence for everyone in the class; a course taken instead stays private.
    const shared = drafts.filter((d) => isOwnCopy(d) && hasSyllabus(d));
    const mine = drafts.filter((d) => !isOwnCopy(d) && named(d));
    let id = created;
    try {
      if (!id) {
        setBusy("Starting the map…");
        const course = await api.addCourse(code, file, paste ? text : "", shared.map((d) => ({ code: d.code, file: d.file, text: d.text })));
        id = course.id;
        setCreated(id);
        rememberCourse(id);
        setDrafts((ds) => ds.filter((d) => !shared.includes(d)));
      }
      if (Object.keys(met).length) await api.updateMe(id, { met, draft: true });
      for (const d of mine) {
        setBusy(`Saving ${d.code.trim()}…`);
        await api.addPriorCourse(id, d);
        setDrafts((ds) => ds.filter((x) => x.uid !== d.uid));
      }
      go(`/c/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  const ready = code.trim().length >= 3 && (paste ? text.trim().length > 80 : file != null) && open.length === 0;
  return (
    <div className="add-course">
      <div className="field">
        <label className="field-label" htmlFor="code">Course number</label>
        <input id="code" type="text" placeholder="e.g. DS 612" value={code} autoComplete="off" disabled={created != null}
               onChange={(e) => { setCode(e.target.value); setEntry(null); setLookup("idle"); setMet({}); }} onBlur={check} />
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

      <div className="field">
        <span className="field-label">The prerequisites you took</span>
        <span className="small muted">
          {groups.length > 0
            ? "What you were taught depends on the courses you took, so the map checks those. A syllabus (file or pasted text) gets every concept a quoted answer: taught there, or not."
            : "If this course lists prerequisites, we ask how you met each one once the syllabus is read. You can already add courses you took, at any school."}
        </span>
        <PrereqQuestions groups={groups} met={met} onMet={setMet} drafts={drafts} onDrafts={setDrafts}
                         ownCopyNote="used for everyone who joins this course" />
      </div>

      <p className="muted small">
        Instructor names, emails and phone numbers are removed before a syllabus is stored or sent to AI. Syllabi are course materials: don't
        share one outside your class without the instructor's OK. A course you took somewhere else stays private to you.
      </p>
      <div className="row-actions">
        {account.mode === "firebase" && !account.signedIn ? (
          <button className="btn primary" disabled={busy != null} onClick={() => signInWithGoogle().catch((e) => setError((e as Error).message))}>
            Sign in with Google to map it
          </button>
        ) : (
          <button className="btn primary" disabled={!ready || busy != null} onClick={submit}>
            {busy ? <><Spinner /> {busy}</> : created ? "Try again" : "Map my course"}
          </button>
        )}
        {open.length > 0 && <span className="small notice warn">First say which of {open.map(orList).join("; and which of ")} you took.</span>}
        {error && <span className="error-text">{error}</span>}
        {error && created && <a className="btn ghost small" href={`#/c/${created}`}>Skip this and open the course</a>}
      </div>
    </div>
  );
}

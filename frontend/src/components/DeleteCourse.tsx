import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { go } from "../App";
import { api, forgetCourse, type CourseDetail } from "../lib/api";
import { useDialog } from "../lib/useDialog";
import { Icon, Spinner } from "./ui";

function ConfirmDelete({ course, onClose }: { course: CourseDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const name = course.confirm_name ?? course.code;
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useDialog<HTMLDivElement>(() => { if (!busy) onClose(); });
  const squash = (s: string) => s.split(/\s+/).filter(Boolean).join(" ").toLowerCase();
  const matches = squash(typed) === squash(name);
  const students = course.students ?? 0;

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api.deleteCourse(course.id, typed);
      forgetCourse(course.id);
      qc.removeQueries({ predicate: (q) => q.queryKey.includes(course.id) });
      await qc.invalidateQueries({ queryKey: ["mine"] });
      await qc.invalidateQueries({ queryKey: ["joined"] });
      go("/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <div className="scrim" onClick={() => { if (!busy) onClose(); }} />
      <div className="modal delete-modal" ref={dialog} tabIndex={-1} role="alertdialog" aria-modal="true" aria-labelledby="delete-title" aria-describedby="delete-what">
        <div className="modal-head">
          <h2 id="delete-title">Delete {name}?</h2>
          <button className="btn ghost close" onClick={onClose} disabled={busy} aria-label="Close"><Icon name="close" /></button>
        </div>
        <div className="modal-body delete-body">
          <p className="notice warn" id="delete-what">
            <Icon name="warn" /> This can't be undone. It deletes the course for everyone, not just for you.
          </p>
          <ul className="small">
            <li>The map, the timeline, the study material and every question.</li>
            <li>{students > 0 ? <><b>{students} student{students === 1 ? "'s" : "s'"}</b> plans, answers, notes and earlier courses</> : "Every student's plan, answers, notes and earlier courses"}.</li>
            <li>The join code <span className="mono">{course.join_code}</span> and links to this course stop working.</li>
            <li>Your requests to correct the map, and the prerequisite syllabi you added.</li>
          </ul>
          <label className="field">
            <span className="small">To confirm, type <b className="mono">{name}</b> below.</span>
            <input type="text" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false}
                   aria-label={`Type ${name} to confirm`} onKeyDown={(e) => { if (e.key === "Enter" && matches && !busy) remove(); }} />
          </label>
          <div className="row-actions">
            <button className="btn danger-solid" disabled={!matches || busy} onClick={remove}>
              {busy ? <><Spinner /> Deleting…</> : `Delete ${name} for everyone`}
            </button>
            <button className="btn ghost" disabled={busy} onClick={onClose}>Cancel</button>
            {error && <span className="error-text">{error}</span>}
          </div>
        </div>
      </div>
    </>
  );
}

/** For whoever added the course: delete it, after typing its number. */
export function DeleteCourse({ course }: { course: CourseDetail }) {
  const [open, setOpen] = useState(false);
  const busy = course.build.status === "queued" || course.build.status === "running";
  return (
    <section className="danger-zone">
      <div>
        <b>Delete this course</b>
        <p className="small muted">Removes it for you and everyone who joined, with all their answers and files. You'll be asked to type {course.confirm_name ?? course.code}.</p>
      </div>
      <button className="btn danger" disabled={busy} onClick={() => setOpen(true)} title={busy ? "Wait until mapping finishes" : undefined}>Delete course…</button>
      {open && <ConfirmDelete course={course} onClose={() => setOpen(false)} />}
    </section>
  );
}

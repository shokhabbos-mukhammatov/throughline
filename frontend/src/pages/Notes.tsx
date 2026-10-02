import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { FileDrop, Icon, Spinner } from "../components/ui";
import { api, type CourseDetail } from "../lib/api";

const KIND = { slides: "Slides", pdf: "PDF", doc: "Document", notes: "Notes", photo: "Photo" } as Record<string, string>;

/** The student's own notes, slides and handouts from earlier courses, matched to this course's map. Private. */
export function NotesTab({ course }: { course: CourseDetail }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["materials", course.id], queryFn: () => api.materials(course.id) });
  const options = course.official_prereqs;
  const elsewhere = course.enrollment?.route === "equivalent" || course.enrollment?.route === "permission";
  const [code, setCode] = useState(course.enrollment?.prereq_taken ?? (elsewhere ? "" : options[0] ?? ""));
  const [other, setOther] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);

  function refresh() {
    qc.invalidateQueries({ queryKey: ["materials", course.id] });
    qc.invalidateQueries({ queryKey: ["course", course.id] });
    qc.invalidateQueries({ queryKey: ["plan", course.id] });
  }

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setLast(null);
    try {
      const m = await api.addMaterial(course.id, file, code || other.trim());
      setLast(m.covers.length ? `${m.filename}: covers ${m.covers.length} concept${m.covers.length === 1 ? "" : "s"} in this course.`
        : `${m.filename}: read ${m.parts} parts, but none of them covers a concept this course needs.`);
      setFile(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="plan-layout">
      <section className="sheet taped">
        <div className="sheet-head">
          <h2>My notes</h2>
          <span className="muted small">Only you can see these. They're never shared with classmates or the class view.</span>
        </div>
        <div className="sheet-body">
          <p>
            Add your notes, slides or handouts from {options.length ? options.join(" or ") : "earlier courses"}, or from the course you took
            instead (at another college counts too). Each one is read page by page
            (or slide by slide) and matched to what {course.code} needs, so your plan can say{" "}
            <i>“review slide 14 of your {options[0] ?? "earlier course's"} slides”</i> before sending you to a textbook.
          </p>
          <div className="prereq-upload">
            <span className="label">Add a file</span>
            <FileDrop file={file} onFile={setFile} accept=".pdf,.pptx,.docx,.txt,.md,image/*" label="Notes file"
                      prompt="Drop slides, a PDF or a photo of your notes here" />
            <div className="form-row">
              {options.length > 0 ? (
                <select value={code} onChange={(e) => setCode(e.target.value)} aria-label="From which course">
                  {options.map((o) => <option key={o} value={o}>{o}</option>)}
                  <option value="">Another course</option>
                </select>
              ) : null}
              {!code && (
                <input type="text" value={other} onChange={(e) => setOther(e.target.value)} maxLength={20}
                       placeholder="Which course? e.g. CSE 206" aria-label="Which course the file is from" />
              )}
              <button className="btn primary small" disabled={!file || busy} onClick={upload}>
                {busy ? <><Spinner /> Reading…</> : <><Icon name="upload" /> Add</>}
              </button>
            </div>
            <span className="small muted">PDF, PowerPoint (.pptx), Word (.docx), text or a photo of handwritten notes · up to 15 MB · reading takes about 10–30 seconds.</span>
            {last && <p className="small">{last}</p>}
            {error && <p className="error-text">{error}</p>}
          </div>

          {isLoading || !data ? <div className="empty"><Spinner /></div> : data.length === 0 ? (
            <div className="empty"><b>No notes yet.</b><span>Your plan uses free textbooks until you add some.</span></div>
          ) : (
            <ul className="plain materials">
              {data.map((m) => (
                <li key={m.id}>
                  <div className="meta" style={{ justifyContent: "space-between" }}>
                    <span><b>{m.filename}</b> <span className="tag">{KIND[m.kind] ?? m.kind}</span>{m.prereq_code && <span className="tag">{m.prereq_code}</span>}</span>
                    <button className="btn ghost small danger" onClick={async () => { await api.deleteMaterial(course.id, m.id); refresh(); }}>Remove</button>
                  </div>
                  {m.covers.length ? (
                    <ul className="covers">
                      {m.covers.map((c) => (
                        <li key={c.concept_id}><a href={`#/c/${course.id}/k/${c.concept_id}`}>{c.name}</a> <span className="muted small">· {c.locs.join(", ")}</span></li>
                      ))}
                    </ul>
                  ) : <p className="small muted">Read {m.parts} parts; none covers a concept this course needs.</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
      <aside className="sheet side pinned">
        <div className="sheet-head"><h3>How matching works</h3></div>
        <div className="sheet-body small">
          <p>Your file is split into pages or slides. For each concept {course.code} needs, the closest passages are found, Gemini checks whether they really cover it, and a match is kept only if its quote is actually in your file.</p>
          <p className="muted">Names, emails and phone numbers are removed before anything is stored. The original file isn't kept, only its text.</p>
        </div>
      </aside>
    </div>
  );
}

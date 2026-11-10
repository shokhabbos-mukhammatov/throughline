import { useState } from "react";
import type { Met, PriorCourse, PriorCourseDraft } from "../lib/api";
import { FileDrop, Icon, Spinner } from "./ui";

export type MetMap = Record<string, Met>;

let drafts_made = 0;
export const emptyDraft = (replaces = "", code = ""): PriorCourseDraft =>
  ({ uid: `d${++drafts_made}`, code, school: "", replaces, file: null, text: "" });
export const hasSyllabus = (d: PriorCourseDraft) => d.file != null || d.text.trim().length >= 20;
export const named = (d: PriorCourseDraft) => d.code.trim().length >= 2;
/** A draft for a listed course itself (the student's copy of its syllabus), not a course taken instead of it. */
export const isOwnCopy = (d: PriorCourseDraft) => d.replaces !== "" && d.replaces === d.code && !d.school;

/** "A or B" requirements nobody has answered yet: these must be answered before the map and the check are trusted. */
export const openChoices = (groups: string[][], met: MetMap) => groups.filter((g) => g.length > 1 && !g.some((code) => met[code]));

export const orList = (codes: string[]) => (codes.length < 2 ? codes.join("") : `${codes.slice(0, -1).join(", ")} or ${codes[codes.length - 1]}`);

const SYLLABUS_TYPES = ".pdf,.docx,.txt,.md,.html,image/*";

function DraftRow({ draft, onChange, onRemove, onAdd, busy, error, fixed }: {
  draft: PriorCourseDraft; onChange: (d: PriorCourseDraft) => void; onRemove: () => void;
  onAdd?: () => void; busy?: boolean; error?: string | null; fixed?: boolean;
}) {
  const [paste, setPaste] = useState(draft.text.length > 0);
  const what = draft.code.trim() || "this course";
  return (
    <div className="prior-draft">
      {!fixed && (
        <div className="form-row">
          <input type="text" value={draft.code} maxLength={40} placeholder="Course, e.g. CSE 206" aria-label="Course you took"
                 onChange={(e) => onChange({ ...draft, code: e.target.value })} />
          <input type="text" value={draft.school} maxLength={80} placeholder="Where, e.g. City College" aria-label="School where you took it"
                 onChange={(e) => onChange({ ...draft, school: e.target.value })} />
        </div>
      )}
      {paste ? (
        <textarea rows={4} value={draft.text} placeholder={`Paste the ${what} syllabus: the topics by week are what matter.`}
                  aria-label={`Syllabus text for ${what}`} onChange={(e) => onChange({ ...draft, text: e.target.value, file: null })} />
      ) : (
        <FileDrop compact file={draft.file} onFile={(f) => onChange({ ...draft, file: f, text: "" })} accept={SYLLABUS_TYPES}
                  label={`Syllabus file for ${what}`} prompt={<>Drop the {what} syllabus here</>} />
      )}
      <div className="form-row">
        <button type="button" className="btn ghost small" onClick={() => { setPaste((p) => !p); onChange({ ...draft, file: null, text: "" }); }}>
          {paste ? "Upload a file instead" : "Paste its text instead"}
        </button>
        {onAdd && (
          <button type="button" className="btn primary small" disabled={busy || !named(draft)} onClick={onAdd}>
            {busy ? <><Spinner /> Reading…</> : <><Icon name="upload" /> Add</>}
          </button>
        )}
        <button type="button" className="btn ghost small" disabled={busy} onClick={onRemove}>Remove</button>
        {!hasSyllabus(draft) && !fixed && <span className="small muted">No syllabus? Add the course anyway; we just can't check what it covered.</span>}
      </div>
      {error && <p className="error-text small">{error}</p>}
    </div>
  );
}

/**
 * How the student met each listed prerequisite, and the earlier courses they add (from any school).
 * `groups`: every group is required; codes inside a group are alternatives.
 * With `onAdd`, each course is uploaded as soon as it is added; without it, drafts wait for the surrounding form.
 */
export function PrereqQuestions({ groups, titles = {}, met, onMet, drafts, onDrafts, saved = [], onFile = [], onAdd, adding = null, errors = {}, ownCopyNote }: {
  groups: string[][]; titles?: Record<string, string>; met: MetMap; onMet: (m: MetMap) => void;
  drafts: PriorCourseDraft[]; onDrafts: (d: PriorCourseDraft[]) => void; saved?: PriorCourse[];
  /** Listed prerequisites whose syllabus the course already has (added with the course): nothing to ask for. */
  onFile?: string[];
  onAdd?: (draft: PriorCourseDraft) => void; adding?: string | null; errors?: Record<string, string>; ownCopyNote?: string;
}) {
  const row = (d: PriorCourseDraft, fixed = false) => (
    <DraftRow key={d.uid} draft={d} fixed={fixed} onChange={(x) => onDrafts(drafts.map((y) => (y.uid === d.uid ? x : y)))}
              onRemove={() => onDrafts(drafts.filter((y) => y.uid !== d.uid))}
              onAdd={onAdd ? () => onAdd(d) : undefined} busy={adding === d.uid} error={errors[d.uid]} />
  );

  return (
    <div className="prereq-q">
      {groups.map((group) => {
        const took = group.filter((code) => met[code] === "took");
        const other = took.length ? null : group.map((code) => met[code]).find((v) => v && v !== "took") ?? null;
        const choice = group.length > 1;
        const key = group.join("|");

        const toggle = (code: string) => {
          const next = took.includes(code) ? took.filter((c) => c !== code) : [...took, code];
          const m = { ...met };
          for (const c of group) {
            if (next.length === 0) delete m[c];
            else m[c] = next.includes(c) ? "took" : "none";
          }
          onMet(m);
          // Keep only the syllabi of the listed courses still marked as taken; an "instead of" course no longer applies.
          onDrafts(drafts.filter((d) => !group.includes(d.replaces) || (isOwnCopy(d) && next.includes(d.replaces))));
        };
        const setOther = (kind: Met) => {
          const m = { ...met };
          for (const c of group) m[c] = kind;
          onMet(m);
          const others = drafts.filter((d) => !group.includes(d.replaces));
          const instead = drafts.filter((d) => group.includes(d.replaces) && !isOwnCopy(d));
          onDrafts(kind !== "elsewhere" ? others : [...others, ...(instead.length || savedInstead.length ? instead : [emptyDraft(group[0])])]);
        };
        // Already saved: courses taken instead of this requirement, and the student's own copies of listed syllabi.
        const savedInstead = saved.filter((p) => p.replaces != null && group.includes(p.replaces) && (p.code !== p.replaces || p.school));
        const savedCopy = (code: string) => saved.some((p) => p.code === code && !p.school);

        return (
          <div key={key} className="prq">
            <span className="prq-name">
              {choice ? <>One of {orList(group)}</> : <>{group[0]}{titles[group[0]] ? <span className="muted"> {titles[group[0]]}</span> : null}</>}
            </span>
            {choice && <span className="small muted">Pick every one you took. What each one taught decides what you're likely to know.</span>}
            <div className="prq-answers" role="group" aria-label={choice ? `Which of ${orList(group)} did you take?` : `How did you meet ${group[0]}?`}>
              {group.map((code) => (
                <button type="button" key={code} className={`pick${took.includes(code) ? " on" : ""}`} aria-pressed={took.includes(code)} onClick={() => toggle(code)}>
                  {choice ? code : "I took it"}
                </button>
              ))}
              <span className="prq-or" aria-hidden>or</span>
              {([["elsewhere", "An equivalent somewhere else"], ["none", choice ? "None of them" : "Didn't take it"], ["unsure", "Not sure"]] as [Met, string][]).map(([kind, label]) => (
                <button type="button" key={kind} className={`pick${other === kind ? " on" : ""}`} aria-pressed={other === kind} onClick={() => setOther(kind)}>{label}</button>
              ))}
            </div>

            {took.map((code) => {
              const own = drafts.find((d) => d.replaces === code && isOwnCopy(d));
              if (onFile.includes(code)) return <span key={code} className="small muted prq-link">The {code} syllabus is already on file for this course, so there's nothing to add.</span>;
              if (savedCopy(code)) return <span key={code} className="small muted prq-link">Your {code} syllabus is added (see below).</span>;
              return own ? (
                <div key={code} className="prq-more">
                  <span className="small"><b>Your {code} syllabus</b>{ownCopyNote ? <span className="muted"> · {ownCopyNote}</span> : null}</span>
                  {row(own, true)}
                </div>
              ) : (
                <button type="button" key={code} className="btn ghost small prq-link" onClick={() => onDrafts([...drafts, emptyDraft(code, code)])}>
                  <Icon name="upload" /> I have the {code} syllabus
                </button>
              );
            })}
            {other === "elsewhere" && (
              <div className="prq-more">
                <span className="small"><b>Which course did you take instead?</b> <span className="muted">Any school. Its syllabus shows what you were actually taught.</span></span>
                {savedInstead.length > 0 && <span className="small">Added: {savedInstead.map((p) => (p.school ? `${p.code} (${p.school})` : p.code)).join(", ")}</span>}
                {drafts.map((d) => (group.includes(d.replaces) && !isOwnCopy(d) ? row(d) : null))}
                {!drafts.some((d) => group.includes(d.replaces) && !isOwnCopy(d)) && (
                  <button type="button" className="btn ghost small prq-link" onClick={() => onDrafts([...drafts, emptyDraft(group[0])])}>
                    Add {savedInstead.length ? "another course" : "the course you took instead"}
                  </button>
                )}
              </div>
            )}
            {other === "none" && <p className="small notice">Then what {choice ? "they teach" : "it teaches"} goes into your plan as things to learn, not just review.</p>}
          </div>
        );
      })}

      <div className="prq extra">
        <span className="prq-name">Other courses that prepared you <span className="muted">(optional)</span></span>
        <span className="small muted">
          Any earlier course at any school: a community college, another university, an online course. Add its syllabus as a file or pasted text
          and we check it against what this course needs.
        </span>
        {drafts.map((d) => (d.replaces === "" ? row(d) : null))}
        <button type="button" className="btn ghost small prq-link" onClick={() => onDrafts([...drafts, emptyDraft()])}>
          <Icon name="upload" /> Add {drafts.some((d) => d.replaces === "") ? "another" : "a"} course
        </button>
      </div>
    </div>
  );
}

/** The earlier courses already saved, with what each syllabus turned out to cover. */
export function PriorCourseList({ items, courseId, total, onRemove }: {
  items: PriorCourse[]; courseId: string; total: number; onRemove: (id: string) => void;
}) {
  if (!items.length) return null;
  return (
    <ul className="plain materials">
      {items.map((p) => (
        <li key={p.id}>
          <div className="meta" style={{ justifyContent: "space-between" }}>
            <span>
              <b>{p.code}</b>
              {p.school && <span className="tag">{p.school}</span>}
              {p.replaces && p.replaces !== p.code && <span className="muted small"> · instead of {p.replaces}</span>}
            </span>
            <button type="button" className="btn ghost small danger" onClick={() => onRemove(p.id)}>Remove</button>
          </div>
          {!p.has_syllabus ? (
            <p className="small muted">No syllabus added, so we can't check what it covered. Remove it and add it again with one.</p>
          ) : p.checked === 0 ? (
            <p className="small muted">Syllabus saved ({p.source}). It's compared with this course as soon as the map is ready.</p>
          ) : p.covers.length ? (
            <>
              <span className="small muted">Syllabus read ({p.source}): it teaches {p.covers.length} of the {total} things this course needs.</span>
              <ul className="covers">
                {p.covers.map((c) => (
                  <li key={c.concept_id}><a href={`#/c/${courseId}/k/${c.concept_id}`}>{c.name}</a> <q className="muted small">{c.quote}</q></li>
                ))}
              </ul>
            </>
          ) : (
            <p className="small muted">Syllabus read ({p.source}): none of the {total} things this course needs is in it.</p>
          )}
        </li>
      ))}
    </ul>
  );
}

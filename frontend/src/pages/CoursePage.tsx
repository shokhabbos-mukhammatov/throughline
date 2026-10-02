import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { go } from "../App";
import { ConceptDrawer } from "../components/ConceptDrawer";
import { Icon, Spinner } from "../components/ui";
import { api, rememberCourse, type CourseDetail } from "../lib/api";
import { AI_LABEL, TIMELINE_LABEL } from "../lib/format";
import { ClassViewTab } from "./ClassView";
import { PrereqMapTab } from "./GraphPage";
import { TimelineTab } from "./MapPage";
import { PlanTab } from "./Readiness";
import { NotesTab } from "./Notes";
import { ReviewTab } from "./Review";
import { Setup } from "./Setup";
import { ShareTab } from "./Share";
import { CheckSession } from "./Tutor";

const STAGES = [
  "Reading the syllabus",
  "Checking the SF State Bulletin",
  "Mapping prerequisites",
  "Resolving concepts and building the graph",
  "Checking what prerequisites taught",
  "Writing study material",
  "Double-checking answer keys",
];

function BuildProgress({ course }: { course: CourseDetail }) {
  const qc = useQueryClient();
  const b = course.build;
  // A coverage re-check runs a single stage that isn't part of a full build.
  const stages = STAGES.includes(b.stage) || !b.stage ? STAGES : [b.stage];
  const current = stages.indexOf(b.stage);
  if (b.status === "error") {
    return (
      <section className="sheet">
        <div className="sheet-body">
          <h2>We couldn't map this syllabus</h2>
          <p className="error-text" style={{ marginTop: 8 }}>{b.error}</p>
          {(b.error_kind ?? "syllabus") === "syllabus" ? (
            <p className="muted" style={{ marginTop: 8 }}>
              Syllabi without any schedule, dated assessments or topic list can't be placed on a timeline. If yours has the schedule on Canvas, paste that page's text instead.
            </p>
          ) : (
            <p className="muted" style={{ marginTop: 8 }}>This isn't a problem with your syllabus. Try again in a few minutes.</p>
          )}
          {course.is_owner && (
            <div className="row-actions" style={{ marginTop: 12 }}>
              <button className="btn" onClick={async () => { await api.rebuild(course.id); qc.invalidateQueries({ queryKey: ["course", course.id] }); }}>Try again</button>
              <a className="btn ghost" href="#/">Add it again</a>
            </div>
          )}
        </div>
      </section>
    );
  }
  return (
    <section className="sheet">
      <div className="sheet-body">
        <h2>Mapping {course.code || "your course"}…</h2>
        <p className="muted" style={{ marginTop: 6 }}>
          Usually about a minute with Gemini: the prerequisites are mapped three times independently and only what the runs agree on is kept.
          You can keep this page open.
        </p>
        <ol className="stages">
          {stages.map((s, i) => (
            <li key={s} className={i < current ? "done" : i === current ? "now" : ""}>
              {i < current ? <Icon name="check" /> : i === current ? <Spinner /> : <span className="dot-ph" />}
              <span>{s}{i === current && b.total ? ` (${b.done} of ${b.total})` : ""}</span>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

function weekLabel(c: CourseDetail): string {
  const w = c.week_now ?? 1;
  const last = Math.max(1, ...(c.timeline ?? []).map((t) => t.week));
  if (w < 1) return `Starts in ${1 - w} week${w === 0 ? "" : "s"}`;
  if (w > last) return "Term is over";
  return `Week ${w} of ${last}`;
}

function CourseHeader({ c }: { c: CourseDetail }) {
  const [open, setOpen] = useState(false);
  const tl = TIMELINE_LABEL[c.timeline_kind];
  const stance = c.ai_policy.stance;
  return (
    <section className={`sheet course-head${open ? " open" : ""}`}>
      <div className="ch-main">
        <h1>{c.code} <span className="ch-title">{c.title}</span></h1>
        <div className="meta">
          <span>{c.term || "Current term"}{c.demo ? " · Sample course (fictional)" : ""}</span>
          <span className="pill strong">{weekLabel(c)}</span>
          <span className="pill ch-extra" title={tl.hint}>{tl.label}</span>
          <span className={`pill ai-${stance}`} title={c.ai_policy.summary}>{AI_LABEL[stance]}</span>
          {!c.engine.online && <span className="pill warn" title={c.engine.label}>Offline mode: no Gemini</span>}
        </div>
      </div>
      <div className="ch-prereq">
        <span className="label">Official prerequisites</span>
        <p className="ch-prereq-text">{c.prereq_text || c.official_prereqs.join(", ") || "None listed"}</p>
        {c.prereq_routes.length > 0 && <p className="small muted ch-extra">Other ways in: {c.prereq_routes.join(" · ")}</p>}
        <button className="btn ghost small" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide" : "Show"} sources and notes</button>
      </div>
      {open && (
        <div className="ch-more">
          {c.bulletin.length > 0 && (
            <div>
              <span className="label">SF State Bulletin</span>
              <ul className="plain">
                {c.bulletin.map((b) => (
                  <li key={b.code}><b>{b.code} {b.title}.</b> {b.description} {b.prerequisites && <span className="muted">Prerequisites: {b.prerequisites}</span>} <span className="muted small">({b.source})</span></li>
                ))}
              </ul>
            </div>
          )}
          {(c.instructor_notes.length > 0 || c.informal_requirements.length > 0) && (
            <div>
              <span className="label">What the syllabus says you need</span>
              <ul className="plain">{[...c.informal_requirements, ...c.instructor_notes].map((n, i) => <li key={i}>“{n}”</li>)}</ul>
            </div>
          )}
          {c.ai_policy.summary && (
            <div>
              <span className="label">AI policy</span>
              <p>{c.ai_policy.summary}</p>
              <p className="small muted">Throughline only helps you review prerequisite concepts. It never touches graded work, so follow this course's policy for assignments.</p>
            </div>
          )}
        </div>
      )}
      {stance === "prohibited" && (
        <p className="notice warn ch-wide">
          <Icon name="warn" /> This course prohibits AI for coursework. Throughline only reviews <i>prerequisite</i> concepts from earlier courses and never helps with assignments. If you're unsure whether that's allowed, ask your instructor.
        </p>
      )}
    </section>
  );
}

export function CoursePage({ id, tab, concept }: { id: string; tab: string; concept?: string }) {
  const [checking, setChecking] = useState(false);
  const { data: c, error } = useQuery({
    queryKey: ["course", id],
    queryFn: () => api.course(id),
    refetchInterval: (q) => (q.state.data && q.state.data.build.status !== "ready" && q.state.data.build.status !== "error" ? 1500 : false),
  });
  useEffect(() => rememberCourse(id), [id]);

  if (error) return <section className="sheet"><div className="empty"><p className="error-text">{(error as Error).message}</p><a href="#/">Back</a></div></section>;
  if (!c) return <section className="sheet"><div className="empty"><Spinner /></div></section>;
  if (c.build.status !== "ready") return <BuildProgress course={c} />;

  const tabs = [
    { id: "plan", label: "My plan" },
    { id: "timeline", label: "Timeline" },
    { id: "map", label: "Prerequisite map" },
    { id: "notes", label: "My notes" },
    ...(c.is_owner ? [{ id: "class", label: "Class view" }, { id: "review", label: "Review map" }] : []),
    { id: "share", label: "Share" },
  ];
  const active = tabs.some((t) => t.id === tab) ? tab : "plan";
  const needsSetup = tab === "setup" || (!c.enrolled && (active === "plan" || active === "timeline" || active === "map" || active === "notes"));

  return (
    <>
      <CourseHeader c={c} />
      {needsSetup ? (
        <Setup course={c} onDone={(check) => { if (check) setChecking(true); go(`/c/${id}/plan`); }} />
      ) : (
        <>
          <nav className="nav" aria-label="Course sections">
            <div className="tabs">
              {tabs.map((t) => (
                <a key={t.id} href={`#/c/${id}/${t.id}`} aria-current={active === t.id ? "page" : undefined}>{t.label}</a>
              ))}
            </div>
            <button className="btn primary small nav-cta" onClick={() => setChecking(true)}><Icon name="check" /> Quick check</button>
          </nav>
          {active === "plan" && <PlanTab course={c} onCheck={() => setChecking(true)} />}
          {active === "timeline" && <TimelineTab course={c} />}
          {active === "map" && <PrereqMapTab course={c} />}
          {active === "notes" && <NotesTab course={c} />}
          {active === "class" && c.is_owner && <ClassViewTab course={c} />}
          {active === "review" && c.is_owner && <ReviewTab course={c} />}
          {active === "share" && <ShareTab course={c} />}
        </>
      )}
      {checking && <CheckSession course={c} onClose={() => { setChecking(false); if (active !== "plan") go(`/c/${id}/plan`); }} />}
      {concept && <ConceptDrawer course={c} conceptId={concept} onClose={() => go(`/c/${id}/${active}`)} />}
    </>
  );
}

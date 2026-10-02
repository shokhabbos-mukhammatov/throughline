import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { go } from "../App";
import { Spinner } from "../components/ui";
import { api, joinedCourses, rememberCourse, type CoursePublic } from "../lib/api";
import { AddCourseForm } from "./Library";

function JoinForm() {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="form-row"
      onSubmit={async (e) => {
        e.preventDefault();
        setError(null);
        try {
          const c = await api.join(code);
          rememberCourse(c.id);
          go(`/c/${c.id}`);
        } catch (err) {
          setError((err as Error).message);
        }
      }}
    >
      <input type="text" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="Class code, e.g. K7Q2MX" aria-label="Class code" maxLength={8} style={{ width: 190 }} />
      <button className="btn" disabled={code.trim().length < 4}>Join</button>
      {error && <span className="error-text">{error}</span>}
    </form>
  );
}

function MyCourses() {
  const { data: owned } = useQuery({ queryKey: ["mine"], queryFn: api.mine });
  const { data: joined } = useQuery({
    queryKey: ["joined"],
    queryFn: async () => {
      const results = await Promise.allSettled(joinedCourses().map((id) => api.course(id)));
      return results.flatMap((r) => (r.status === "fulfilled" ? [r.value as CoursePublic] : []));
    },
  });
  const all = new Map<string, CoursePublic>();
  for (const c of [...(owned ?? []), ...(joined ?? [])]) all.set(c.id, c);
  if (!all.size) return null;
  return (
    <section className="sheet">
      <div className="sheet-head"><h2>Your courses</h2></div>
      <div className="sheet-body course-list">
        {[...all.values()].map((c) => (
          <a key={c.id} className="course-link" href={`#/c/${c.id}`}>
            <b>{c.code || "New course"}</b> <span>{c.title}</span>
            <span className="muted small">{c.term}{c.demo ? " · sample" : ""}{c.build.status !== "ready" ? ` · ${c.build.status === "error" ? "couldn't be mapped" : "mapping…"}` : ""}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

export function Welcome() {
  const [busy, setBusy] = useState(false);
  return (
    <>
      <section className="welcome">
        <div>
          <h1>Your class assumes things you may <mark className="hl">never have been taught.</mark></h1>
          <p className="lede">
            Prerequisites say you're ready. "Or equivalent", a waiver, or a summer off say otherwise. Throughline reads your SF State syllabus and the University Bulletin,
            finds what each week assumes you already know, checks it in a few minutes, and fits a review plan into the time you actually have, before the class that needs it.
          </p>
          <ol className="steps">
            <li><span><b>Add your course.</b> Course number plus the syllabus. We look up the official prerequisites in the Bulletin.</span></li>
            <li><span><b>Find your gaps.</b> Tell us what you've studied, then answer a short adaptive check. Concepts build on each other, so each answer also says something about its neighbours: a few questions place you on the whole map.</span></li>
            <li><span><b>Keep pace.</b> A week-by-week plan with free textbook sections, sized to your weekly time, before each class needs it.</span></li>
          </ol>
          <div className="row-actions" style={{ marginTop: 18 }}>
            <button className="btn" disabled={busy} onClick={async () => {
              setBusy(true);
              const c = await api.sample();
              rememberCourse(c.id);
              go(`/c/${c.id}`);
            }}>
              {busy ? <Spinner /> : null} Try the sample course
            </button>
            <span className="muted small">A fictional course with a simulated class, no AI needed.</span>
          </div>
          <p style={{ marginTop: 14 }}><a href="#/how">How it works: the workflow, the algorithms and their formulas</a></p>
        </div>
        <div className="sheet taped">
          <div className="sheet-head"><h2>Add your course</h2></div>
          <div className="sheet-body">
            <AddCourseForm />
            <hr className="rule" />
            <span className="field-label">Got a class code from your instructor or a classmate?</span>
            <JoinForm />
          </div>
        </div>
      </section>
      <MyCourses />
    </>
  );
}

export function JoinRedirect({ code }: { code: string }) {
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.join(code).then((c) => {
      rememberCourse(c.id);
      window.location.replace(`#/c/${c.id}`);
    }, (e) => setError((e as Error).message));
  }, [code]);
  return <section className="sheet"><div className="empty">{error ? <p className="error-text">{error}</p> : <Spinner />}</div></section>;
}

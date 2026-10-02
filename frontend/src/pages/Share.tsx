import { useState } from "react";
import { QrCode } from "../components/ui";
import type { CourseDetail } from "../lib/api";

export function ShareTab({ course }: { course: CourseDetail }) {
  const [present, setPresent] = useState(false);
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}/#/j/${course.join_code}`;
  return (
    <section className="sheet taped">
      <div className="sheet-head"><h2>Share with your class</h2></div>
      <div className="sheet-body share">
        <QrCode text={link} size={220} />
        <div>
          <span className="label">Class code</span>
          <p className="join-code">{course.join_code}</p>
          <p className="mono small" style={{ wordBreak: "break-all" }}>{link}</p>
          <div className="row-actions" style={{ marginTop: 10 }}>
            <button className="btn" onClick={async () => {
              try { await navigator.clipboard.writeText(link); setCopied(true); } catch { setCopied(false); }
            }}>{copied ? "Copied" : "Copy link"}</button>
            <button className="btn primary" onClick={() => setPresent(true)}>Show on the projector</button>
          </div>
          <p className="small muted" style={{ marginTop: 12 }}>
            Everyone who joins reuses this course map, so nobody has to upload the syllabus again. Each student's answers stay private; {course.is_owner ? "you" : "whoever added the course"} only see class totals, and only once 5 or more students have answered.
          </p>
        </div>
      </div>
      {present && (
        <div className="present" role="dialog" aria-label="Join code" onClick={() => setPresent(false)}>
          <QrCode text={link} size={Math.min(window.innerWidth, window.innerHeight) * 0.6} />
          <p className="join-code big">{course.join_code}</p>
          <p>{course.code} · scan to check your prerequisites (tap anywhere to close)</p>
        </div>
      )}
    </section>
  );
}

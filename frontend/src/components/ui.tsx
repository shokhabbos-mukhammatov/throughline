import qrcode from "qrcode-generator";
import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Coverage, Resource, Status } from "../lib/api";
import { COVERAGE_LABEL, STATUS_HINT, STATUS_LABEL, pct } from "../lib/format";

/* ---------- icons (inline, stroke follows currentColor) ---------- */

export function StatusIcon({ status, size = 14 }: { status: Status; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.8, "aria-hidden": true } as const;
  switch (status) {
    case "ready":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.5" />
          <path d="M5 8.2l2 2 4-4.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "likely":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.5" />
          <path d="M8 1.5a6.5 6.5 0 0 1 0 13z" fill="currentColor" stroke="none" />
        </svg>
      );
    case "refresh":
      return (
        <svg {...common}>
          <path d="M13 8a5 5 0 1 1-1.6-3.7" strokeLinecap="round" />
          <path d="M11.8 1.8v2.9H8.9" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "learn":
      return (
        <svg {...common}>
          <path d="M2 4.5l6-2.5 6 2.5-6 2.5z" strokeLinejoin="round" />
          <path d="M4.5 6v3.5c0 1 1.6 2 3.5 2s3.5-1 3.5-2V6" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="6.5" strokeDasharray="2.2 2.4" />
        </svg>
      );
  }
}

export function Icon({ name, size = 15 }: { name: "plan" | "check" | "close" | "upload" | "arrow" | "clock" | "warn" | "link" | "lock" | "eye"; size?: number }) {
  const p = { width: size, height: size, viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true } as const;
  switch (name) {
    case "plan":
      return <svg {...p}><path d="M3 4h10M3 8h7M3 12h5" /></svg>;
    case "check":
      return <svg {...p}><rect x="2.5" y="2.5" width="11" height="11" rx="1.5" /><path d="M5 8l2 2 4-4" /></svg>;
    case "close":
      return <svg {...p}><path d="M4 4l8 8M12 4l-8 8" /></svg>;
    case "upload":
      return <svg {...p}><path d="M8 11V3M5 6l3-3 3 3" /><path d="M3 12v1.5h10V12" /></svg>;
    case "arrow":
      return <svg {...p}><path d="M3 8h10M9 4l4 4-4 4" /></svg>;
    case "clock":
      return <svg {...p}><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></svg>;
    case "warn":
      return <svg {...p}><path d="M8 2l6.5 11.5h-13z" /><path d="M8 6.5v3M8 11.8v.2" /></svg>;
    case "link":
      return <svg {...p}><path d="M6.5 9.5l3-3M7 4.5l1.2-1.2a2.8 2.8 0 0 1 4 4L11 8.5M9 11.5l-1.2 1.2a2.8 2.8 0 0 1-4-4L5 7.5" /></svg>;
    case "lock":
      return <svg {...p}><rect x="3.5" y="7" width="9" height="6.5" rx="1" /><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" /></svg>;
    case "eye":
      return <svg {...p}><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8 12.1 12.5 8 12.5 1.5 8 1.5 8z" /><circle cx="8" cy="8" r="2" /></svg>;
  }
}

export function Wordmark({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <rect x="1" y="1" width="38" height="38" rx="6" fill="var(--accent)" />
      <path d="M8 28 C 16 28, 15 12, 23 12 S 32 20, 32 20" fill="none" stroke="var(--accent-ink)" strokeWidth="3" strokeLinecap="round" />
      <circle cx="8" cy="28" r="3.4" fill="var(--accent-ink)" />
      <circle cx="32" cy="20" r="3.4" fill="var(--gold)" />
    </svg>
  );
}

export function StatusChip({ status }: { status: Status }) {
  return (
    <span className={`status ${status}`} title={STATUS_HINT[status]}>
      <StatusIcon status={status} />
      {STATUS_LABEL[status]}
    </span>
  );
}

export function CoverageTag({ coverage, covered_by }: { coverage: Coverage; covered_by: string | null }) {
  const c = COVERAGE_LABEL[coverage];
  const text = coverage === "listed" || coverage === "likely" ? `${c.label} ${covered_by ?? "a prerequisite"}` : c.label;
  return <span className={`tag cov-${coverage}`} title={c.hint}>{text}</span>;
}

/** How likely the student knows a concept, from the knowledge model. */
export function ProbBar({ p, label = true }: { p: number; label?: boolean }) {
  const band = p >= 0.85 ? "b4" : p >= 0.6 ? "b3" : p >= 0.3 ? "b2" : "b1";
  return (
    <span className="prob" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(p * 100)} aria-label="Estimated chance you know it">
      <span className="prob-track"><span className={`prob-fill ${band}`} style={{ transform: `scaleX(${Math.max(0.03, p)})` }} /><i style={{ left: "60%" }} /><i style={{ left: "85%" }} /></span>
      {label && <span className="mono small">{pct(p)}</span>}
    </span>
  );
}

/* ---------- file picker: drop zone with a real (visually hidden) file input ---------- */

export function FileDrop({ file, onFile, accept, prompt, label, compact = false }: {
  file: File | null; onFile: (f: File | null) => void; accept: string; prompt: ReactNode; label: string; compact?: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!file && input.current) input.current.value = ""; }, [file]);
  return (
    <label
      className={`drop${compact ? " compact" : ""}${over ? " over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) onFile(e.dataTransfer.files[0]); }}
    >
      <Icon name="upload" /> {file ? <b>{file.name}</b> : <>{prompt} or <u>choose a file</u></>}
      <input ref={input} type="file" className="visually-hidden" accept={accept} aria-label={label}
             onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
    </label>
  );
}

/* ---------- markdown with math ---------- */

const MathMarkdown = lazy(() => import("./MathMarkdown"));

export function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <Suspense fallback={<p>{text}</p>}>
        <MathMarkdown text={text} />
      </Suspense>
    </div>
  );
}

export function ResourceList({ resources }: { resources: Resource[] }) {
  if (!resources.length) return <p className="muted small">No free resource in our catalog fits this one yet.</p>;
  return (
    <ul className="resources">
      {resources.map((r, i) => (
        <li key={i}>
          {r.url ? (
            <a href={r.url} target="_blank" rel="noreferrer">
              {r.title}
            </a>
          ) : (
            <b>{r.title}</b>
          )}
          {r.detail && <span className="muted"> · {r.detail}</span>}
          {r.kind === "syllabus" && <span className="tag">Recommended in your syllabus</span>}
        </li>
      ))}
    </ul>
  );
}

export function Spinner() {
  return (
    <span className="typing" role="status" aria-label="Working">
      <i />
      <i />
      <i />
    </span>
  );
}

export function QrCode({ text, size = 200 }: { text: string; size?: number }) {
  const path = useMemo(() => {
    const qr = qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c + 4},${r + 4}h1v1h-1z`;
    return { d, n: n + 8 };
  }, [text]);
  return (
    <svg className="qr" width={size} height={size} viewBox={`0 0 ${path.n} ${path.n}`} role="img" aria-label={`QR code for ${text}`} shapeRendering="crispEdges">
      <rect width={path.n} height={path.n} fill="#fff" />
      <path d={path.d} fill="#000" />
    </svg>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

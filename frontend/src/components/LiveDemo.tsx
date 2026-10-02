import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { Icon } from "./ui";

/*
 * An auto-playing walkthrough of the app in a browser frame. Concepts, percentages and minutes come from the
 * built-in sample course (DEMO 410, fictional prerequisite DEMO 212); call counts and timing from real syllabi.
 */

const SCENE_MS = 5200;

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const m = matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduced;
}

export function useInView<T extends Element>(): [React.RefObject<T>, boolean] {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // "on screen" = some of it is in the middle band of the viewport, so tall sections count too
    const io = new IntersectionObserver(([e]) => setSeen(e.isIntersecting), { rootMargin: "-25% 0px -25% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, seen];
}

function Count({ to, ms, run }: { to: number; ms: number; run: boolean }) {
  const [n, setN] = useState(run ? 0 : to);
  useEffect(() => {
    if (!run) { setN(to); return; }
    setN(0);
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setN(Math.round(to * k));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, ms, run]);
  return <span className="mono">{n}</span>;
}

const d = (s: number) => ({ "--d": `${s}s` }) as CSSProperties;

function AddCourse() {
  return (
    <div className="ld-scene ld-add">
      <div className="ld-slip">
        <b className="ld-h">Add your course</b>
        <span className="ld-label">Course number</span>
        <span className="ld-input"><span className="ld-typed mono">DEMO 410</span></span>
        <span className="ld-hit ld-in" style={d(1.2)}><b>DEMO 410 Applied Machine Learning for Scientists</b> · Prerequisites: DEMO 212</span>
        <span className="ld-label">Syllabus</span>
        <span className="ld-drop"><span className="ld-file ld-fall" style={d(1.9)}><Icon name="upload" /> demo410_syllabus.pdf</span></span>
        <span className="ld-btn ld-press" style={d(3.2)}>Map my course</span>
      </div>
    </div>
  );
}

const STAGES = [
  ["Reading the syllabus", "timeline · prerequisites · AI policy"],
  ["Looking up the SF State Bulletin", "DEMO 212 listed"],
  ["Mapping prior knowledge", "3 independent Gemini runs"],
  ["Merging concepts", "11 concepts, 3 “builds on” links"],
  ["Checking the prerequisite's syllabus", "quotes verified"],
  ["Writing study packs and questions", "answer keys re-solved blind"],
];

function Build({ run }: { run: boolean }) {
  return (
    <div className="ld-scene ld-build">
      <div className="ld-slip">
        <b className="ld-h">Mapping DEMO 410</b>
        <ol className="ld-stages">
          {STAGES.map(([t, s], i) => (
            <li key={t} className="ld-in" style={d(0.3 + i * 0.65)}>
              <span className="ld-tick ld-pop" style={d(0.6 + i * 0.65)}><Icon name="check" /></span>
              <span><b>{t}</b><span className="muted small"> · {s}</span></span>
            </li>
          ))}
        </ol>
        <span className="ld-meter">Gemini calls on a real SF State syllabus: <Count to={19} ms={4200} run={run} /> · about 80–100 seconds</span>
      </div>
    </div>
  );
}

const MAP_CARDS = [
  { id: "a", name: "Descriptive Statistics", x: 4, y: 14, pin: "var(--good)" },
  { id: "b", name: "Vectors and the Dot Product", x: 4, y: 58, pin: "var(--gold)" },
  { id: "c", name: "Simple Linear Regression", x: 37, y: 28, pin: "var(--good)" },
  { id: "d", name: "Matrix Multiplication", x: 37, y: 66, pin: "var(--gold)" },
  { id: "e", name: "Multiple Linear Regression", x: 70, y: 40, pin: "var(--gold)" },
];
const MAP_LINKS: [string, string, string][] = [["a", "c", "var(--c2)"], ["b", "d", "var(--c8)"], ["c", "e", "var(--c3)"]];

function MapScene() {
  const at = (id: string) => MAP_CARDS.find((c) => c.id === id)!;
  return (
    <div className="ld-scene ld-map">
      {MAP_CARDS.map((c, i) => (
        <span key={c.id} className="ld-card ld-pop" style={{ left: `${c.x}%`, top: `${c.y}%`, ...d(0.2 + i * 0.22), "--pin": c.pin } as CSSProperties}>
          <b>{c.name}</b>
        </span>
      ))}
      <svg className="ld-strings" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        {MAP_LINKS.map(([s, t, color], i) => {
          const a = at(s), b = at(t);
          const x1 = a.x + 13, y1 = a.y, x2 = b.x + 13, y2 = b.y;
          return <path key={s + t} d={`M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 + 8} ${x2},${y2}`}
                       className="ld-string ld-draw" style={{ stroke: color, ...d(1.6 + i * 0.5) }} />;
        })}
      </svg>
      <span className="ld-caption ld-in" style={d(3.2)}>Pin colour: taught in DEMO 212 (green) or not in the listed prerequisites (gold)</span>
    </div>
  );
}

function Check() {
  return (
    <div className="ld-scene ld-check">
      <div className="ld-slip">
        <span className="ld-label">Quick check · Simple Linear Regression</span>
        <b className="ld-q">A model predicts exam score from hours studied: ŷ = 20 + 3x. What does the 3 mean?</b>
        <span className="ld-choice">A student who does not study scores 3 points</span>
        <span className="ld-choice ld-pick" style={d(1.3)}>Each additional hour is associated with about 3 more points</span>
        <span className="ld-verdict ld-in" style={d(1.9)}><b className="good">Correct</b> · Simple Linear Regression 44% → 74%</span>
        <span className="ld-bars ld-in" style={d(2.6)}>
          <span>Descriptive Statistics <i className="ld-bar"><i className="ld-fill" style={{ "--from": 0.72, "--to": 0.87, ...d(2.8) } as CSSProperties} /></i> <span className="mono">87%</span></span>
          <span>Multiple Linear Regression <i className="ld-bar"><i className="ld-fill" style={{ "--from": 0.15, "--to": 0.26, ...d(2.8) } as CSSProperties} /></i> <span className="mono">26%</span></span>
        </span>
        <span className="ld-caption ld-in" style={d(3.4)}>One answer moved the concepts it builds on and the ones that build on it.</span>
      </div>
    </div>
  );
}

const PLAN = [
  ["Python Fundamentals", "3 min", "Already in use", true],
  ["Descriptive Statistics", "15 min", "Finish by Oct 2 · comes before Simple Linear Regression", false],
  ["Simple Linear Regression", "20 min", "Needed now", true],
  ["Multiple Linear Regression", "25 min", "Needed now", true],
] as const;

function Plan() {
  return (
    <div className="ld-scene ld-plan">
      <div className="ld-slip">
        <b className="ld-h">Your pace plan · 3 h a week</b>
        <span className="ld-tape">This week</span>
        {PLAN.map(([n, m, due, hot], i) => (
          <span key={n} className="ld-row ld-slide" style={d(0.4 + i * 0.45)}>
            <b>{n}</b><span className="mono">{m}</span><span className={hot ? "late" : "muted small"}>{due}</span>
          </span>
        ))}
        <span className="ld-caption ld-in" style={d(2.6)}>Foundations come first; everything is done before the class that needs it.</span>
      </div>
    </div>
  );
}

function Notes() {
  return (
    <div className="ld-scene ld-notes">
      <div className="ld-slip">
        <b className="ld-h">My notes</b>
        <span className="ld-drop"><span className="ld-file ld-fall" style={d(0.3)}><Icon name="upload" /> regression_slides.pdf</span></span>
        <span className="ld-verdict ld-in" style={d(1.3)}>Read 25 slides · covers <b>Simple Linear Regression</b> and <b>Multiple Linear Regression</b></span>
        <span className="ld-row ld-slide" style={d(2.1)}>
          <b>Simple Linear Regression</b><span className="mono">20 min</span>
          <span className="ld-src"><span className="src-tag notes">Your notes</span> regression_slides.pdf · slide 15</span>
        </span>
        <span className="ld-caption ld-in" style={d(2.9)}>Your own slides come first, then the free textbook section. Matches are checked by Gemini and quoted from the file.</span>
      </div>
    </div>
  );
}

const SCENES: { title: string; body: (run: boolean) => ReactNode }[] = [
  { title: "Add a course", body: () => <AddCourse /> },
  { title: "Gemini maps it", body: (run) => <Build run={run} /> },
  { title: "The map", body: () => <MapScene /> },
  { title: "Quick check", body: () => <Check /> },
  { title: "Pace plan", body: () => <Plan /> },
  { title: "Your notes", body: () => <Notes /> },
];

export function LiveDemo() {
  const reduced = usePrefersReducedMotion();
  const [box, visible] = useInView<HTMLDivElement>();
  const [scene, setScene] = useState(0);
  const [paused, setPaused] = useState(false);
  const [round, setRound] = useState(0); // remounts a scene so its animation restarts
  const playing = visible && !paused && !reduced;

  useEffect(() => { if (playing) setRound((r) => r + 1); }, [playing]);

  useEffect(() => {
    if (!playing) return;
    const t = setTimeout(() => { setScene((s) => (s + 1) % SCENES.length); setRound((r) => r + 1); }, SCENE_MS);
    return () => clearTimeout(t);
  }, [playing, scene, round]);

  const show = (i: number) => { setScene(i); setRound((r) => r + 1); };
  return (
    <div className={`ld${playing ? "" : " ld-still"}${reduced ? " ld-reduced" : ""}`} ref={box}>
      <div className="ld-window">
        <div className="ld-chrome" aria-hidden>
          <span className="ld-dots"><i /><i /><i /></span>
          <span className="ld-url">throughline · sample course</span>
        </div>
        <div className="ld-stage" aria-live="off" key={round}>
          {SCENES[scene].body(playing)}
        </div>
      </div>
      <div className="ld-controls">
        <button className="btn small" onClick={() => setPaused((p) => !p)} disabled={reduced} aria-pressed={paused}>
          {paused || reduced ? "Play" : "Pause"}
        </button>
        <ol className="ld-steps">
          {SCENES.map((s, i) => (
            <li key={s.title}>
              <button className={i === scene ? "on" : ""} aria-current={i === scene ? "step" : undefined} onClick={() => show(i)}>
                <span className="ld-step-n">{i + 1}</span> {s.title}
                {i === scene && playing && <i className="ld-progress" key={round} style={{ animationDuration: `${SCENE_MS}ms` }} />}
              </button>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

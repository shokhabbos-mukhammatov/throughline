import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { go } from "../App";
import { LiveDemo, useInView } from "../components/LiveDemo";
import { TechCarousel } from "../components/TechCarousel";
import { Icon, Markdown, Spinner } from "../components/ui";
import { api, rememberCourse } from "../lib/api";

/* ---------- live knowledge-space demo: the same model as backend/throughline/mastery.py ---------- */

const SLIP = 0.1, GUESS = 0.25, PRIOR = 0.5, READY = 0.85, LIKELY = 0.6, MIN_GAIN = 0.02;

type DemoConcept = { id: string; name: string; col: number; parents: number[] };
const CONCEPTS: DemoConcept[] = [
  { id: "stats", name: "Descriptive statistics", col: 0, parents: [] },
  { id: "prob", name: "Basic probability", col: 0, parents: [] },
  { id: "slr", name: "Simple linear regression", col: 1, parents: [0] },
  { id: "mlr", name: "Multiple linear regression", col: 2, parents: [2] },
];
const N = CONCEPTS.length;

/** Prerequisite-closed subsets of the graph, as bitmasks. */
const STATES: number[] = Array.from({ length: 1 << N }, (_, s) => s).filter((s) =>
  CONCEPTS.every((c, i) => !(s & (1 << i)) || c.parents.every((p) => s & (1 << p))));

type Answer = { i: number; correct: boolean };

function posterior(answers: Answer[]): number[] {
  const w = STATES.map((s) => {
    let p = 1;
    for (let i = 0; i < N; i++) p *= s & (1 << i) ? PRIOR : 1 - PRIOR;
    for (const a of answers) {
      const known = !!(s & (1 << a.i));
      p *= a.correct ? (known ? 1 - SLIP : GUESS) : (known ? SLIP : 1 - GUESS);
    }
    return p;
  });
  const total = w.reduce((a, b) => a + b, 0);
  return w.map((x) => x / total);
}

const marginals = (post: number[]) => CONCEPTS.map((_, i) => STATES.reduce((acc, s, k) => acc + (s & (1 << i) ? post[k] : 0), 0));
const H = (p: number) => (p <= 1e-9 || p >= 1 - 1e-9 ? 0 : -(p * Math.log2(p) + (1 - p) * Math.log2(1 - p)));
const totalH = (post: number[]) => marginals(post).reduce((a, p) => a + H(p), 0);

/** Expected reduction in total uncertainty (bits) about all four concepts from one question on concept i. */
function gain(answers: Answer[], i: number): number {
  const post = posterior(answers);
  const pRight = STATES.reduce((acc, s, k) => acc + post[k] * (s & (1 << i) ? 1 - SLIP : GUESS), 0);
  const after = pRight * totalH(posterior([...answers, { i, correct: true }])) + (1 - pRight) * totalH(posterior([...answers, { i, correct: false }]));
  return totalH(post) - after;
}

function label(p: number, answered: boolean): string {
  if (!answered) return "No answers yet";
  return p >= READY ? "Ready" : p >= LIKELY ? "Probably known" : "Needs review";
}

function KnowledgeDemo() {
  const [answers, setAnswers] = useState<Answer[]>([]);
  const [last, setLast] = useState<string | null>(null);
  const board = useRef<HTMLDivElement>(null);
  const cards = useRef<(HTMLDivElement | null)[]>([]);
  const [pins, setPins] = useState<{ x: number; y: number }[]>([]);

  const p = useMemo(() => marginals(posterior(answers)), [answers]);
  const gains = useMemo(() => CONCEPTS.map((_, i) => gain(answers, i)), [answers]);
  const best = gains.indexOf(Math.max(...gains));
  const stop = gains[best] < MIN_GAIN;

  useLayoutEffect(() => {
    const el = board.current;
    if (!el) return;
    const measure = () => {
      const box = el.getBoundingClientRect();
      setPins(cards.current.map((c, i) => {
        if (!c) return { x: 0, y: 0 };
        const r = c.getBoundingClientRect();
        const out = CONCEPTS.some((d) => d.parents.includes(i)), into = CONCEPTS[i].parents.length > 0;
        const dx = out && !into ? r.width - 16 : into && !out ? 22 : r.width / 2 + 6;
        return { x: r.left - box.left + dx, y: r.top - box.top + 16 };
      }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  function answer(i: number, correct: boolean) {
    const before = p;
    const next = [...answers, { i, correct }];
    const after = marginals(posterior(next));
    const moved = CONCEPTS.map((c, j) => ({ c, j, d: after[j] - before[j] }))
      .filter(({ j, d }) => j !== i && Math.abs(d) >= 0.02)
      .map(({ c, j }) => `${c.name} ${Math.round(before[j] * 100)}% → ${Math.round(after[j] * 100)}%`);
    setLast(`${correct ? "Right" : "Wrong"} on ${CONCEPTS[i].name}: ${Math.round(before[i] * 100)}% → ${Math.round(after[i] * 100)}%.` +
      (moved.length ? ` Through the graph: ${moved.join(", ")}.` : " Nothing else moves: no concept here builds on it or under it."));
    setAnswers(next);
  }

  const edges = CONCEPTS.flatMap((c, i) => c.parents.map((src) => [src, i] as const));
  return (
    <div className="kdemo">
      <div className="kdemo-board" ref={board}>
        {[0, 1, 2].map((col) => (
          <div key={col} className="kdemo-col">
            <span className="label">{["Start here", "Builds on that", "Then"][col]}</span>
            {CONCEPTS.map((c, i) => c.col !== col ? null : (
              <div key={c.id} ref={(el) => { cards.current[i] = el; }}
                   className={`kdemo-card${!stop && i === best ? " next" : ""}`} style={{ "--tilt": `${[-0.2, 0.25, -0.15, 0.2][i]}deg` } as CSSProperties}>
                <b>{c.name}</b>
                <span className="kdemo-p">
                  <span className="kdemo-bar"><i style={{ transform: `scaleX(${Math.max(0.03, p[i])})` }} /></span>
                  <span className="mono">{Math.round(p[i] * 100)}%</span>
                </span>
                <span className="small muted">{label(p[i], answers.length > 0)}</span>
                <span className="small muted mono">{gains[i].toFixed(2)} bits if asked</span>
                <span className="kdemo-actions">
                  <button className="btn small" onClick={() => answer(i, true)} aria-label={`Answer ${c.name} right`}><Icon name="check" /> Right</button>
                  <button className="btn small" onClick={() => answer(i, false)} aria-label={`Answer ${c.name} wrong`}><Icon name="close" /> Wrong</button>
                </span>
                {!stop && i === best && <span className="kdemo-next">Asked next</span>}
              </div>
            ))}
          </div>
        ))}
        <svg className="board kdemo-strings" aria-hidden>
          <defs>
            <filter id="wool-demo" x="-5%" y="-20%" width="110%" height="140%">
              <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="3" result="fuzz" />
              <feDisplacementMap in="SourceGraphic" in2="fuzz" scale="2.2" xChannelSelector="R" yChannelSelector="G" result="yarn" />
              <feDropShadow in="yarn" dx="1.5" dy="2.5" stdDeviation="1.2" floodColor="#000" floodOpacity="0.28" />
            </filter>
            <linearGradient id="steel-demo" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="#f4f6f7" />
              <stop offset="0.5" stopColor="#a3aab1" />
              <stop offset="1" stopColor="#575e65" />
            </linearGradient>
          </defs>
          {pins.length === N && edges.map(([a, b]) => {
            const p1 = pins[a], p2 = pins[b];
            const sag = Math.min(18, 5 + Math.hypot(p2.x - p1.x, p2.y - p1.y) * 0.04);
            const d = `M${p1.x},${p1.y} Q${(p1.x + p2.x) / 2},${(p1.y + p2.y) / 2 + sag} ${p2.x},${p2.y}`;
            return (
              <g key={`${a}-${b}`} className="thread" style={{ "--t": `var(--c${a + 1})` } as CSSProperties} filter="url(#wool-demo)">
                <path className="fuzz" d={d} /><path className="yarn" d={d} /><path className="ply" d={d} /><path className="shine" d={d} />
              </g>
            );
          })}
          {pins.length === N && pins.map((pt, i) => (
            <g key={i} className="pin" style={{ "--pin": "var(--accent)" } as CSSProperties} transform={`translate(${pt.x} ${pt.y})`}>
              <polygon className="pin-shadow" points="-4.6,-8.4 -1.8,-10 2.4,1.6" />
              <ellipse className="pin-shadow" cx={-3} cy={-8.5} rx={6} ry={4.6} />
              <polygon className="pin-needle" points="-9,-10.6 -5.4,-13 0.4,0.6" fill="url(#steel-demo)" />
              <circle className="pin-head" cx={-8} cy={-13} r={6.5} />
              <circle className="pin-shine" cx={-10.2} cy={-15.4} r={2} />
            </g>
          ))}
        </svg>
      </div>
      <div className="kdemo-foot">
        <p className="small" aria-live="polite">
          {last ?? `Every concept has a ${PRIOR * 100}% prior, yet the graph alone already moves them: only ${STATES.length} of ${1 << N} knowledge states are possible, because nobody knows multiple regression without simple regression. So the foundation starts at 75% and the top of the chain at 25%.`}
          {stop && " The check would stop here: no question is worth 0.02 bits any more."}
        </p>
        <button className="btn ghost small" onClick={() => { setAnswers([]); setLast(null); }} disabled={!answers.length}>Reset</button>
      </div>
    </div>
  );
}

/* ---------- page ---------- */

const BUILD = [
  { n: 1, name: "Read", gemini: "Extracts the timeline, prerequisite statement, \"or equivalent\" routes and AI policy from a PDF, .docx, text or photo.", code: "Removes instructor names, emails and phones first; reconciles weeks and dates into one term calendar." },
  { n: 2, name: "Record", gemini: null, code: "Looks the course and its prerequisites up in the SF State Bulletin (CourseLeaf parser, verified snapshot fallback)." },
  { n: 3, name: "Map", gemini: "Three independent runs, each from a different angle and item order, propose the prior knowledge every week relies on.", code: "Drops item ids the model invented." },
  { n: 4, name: "Resolve", gemini: "Embeddings; a same-concept judge only for borderline pairs.", code: "Union-find merges names; majority vote keeps concepts; the graph is made acyclic and transitively reduced." },
  { n: 5, name: "Evidence", gemini: "Judges whether a listed prerequisite taught each concept, from retrieved passages only.", code: "Hybrid BM25 + embedding search; rejects any quote that isn't in the passage it cites." },
  { n: 6, name: "Study packs", gemini: "Writes a refresher, a learn path and three questions per concept.", code: "Resources only from a checked catalog of free textbooks; answer positions reshuffled." },
  { n: 7, name: "Verify", gemini: "Answers every question again, blind.", code: "Questions whose keys disagree stay hidden until a person approves them." },
];

const STUDENT = [
  { n: "A", name: "Set up", text: "How you met the prerequisite, your weekly time, and what you've studied before." },
  { n: "B", name: "Quick check", text: "At most 8 questions, each chosen for what it tells us; one answer moves its neighbours." },
  { n: "C", name: "Pace plan", text: "Foundations first, everything done before the class that needs it, inside your weekly time." },
  { n: "D", name: "Study", text: "Your own notes first (the exact page or slide), then the free textbook section, a refresher and practice." },
];

const ALGORITHMS: { title: string; where: string; what: string; math: string; note?: string }[] = [
  {
    title: "Self-consistency mapping",
    where: "mapping.py",
    what: "Gemini maps the syllabus three times, independently. A concept, requirement or relation survives only if most runs proposed it, and the share of runs becomes its confidence.",
    math: String.raw`$$
\text{keep}(c) \iff v(c) \ge \left\lceil \tfrac{S}{2} \right\rceil,\qquad \text{conf}(c) = \frac{v(c)}{S},\qquad S = 3
$$`,
    note: "v(c) is the number of runs that proposed c.",
  },
  {
    title: "Entity resolution",
    where: "graph.py",
    what: "\"Linear regression\", \"OLS\" and \"least squares\" become one concept. Library aliases merge first; then embedding similarity; only the ambiguous band goes to the model. Union-find turns accepted pairs into clusters.",
    math: String.raw`$$
\cos(u,v)=\frac{u\cdot v}{\lVert u\rVert\,\lVert v\rVert}\quad\begin{cases}\ge 0.93 & \text{merge}\\[2pt] [0.82,\,0.93) & \text{ask Gemini}\\[2pt] < 0.82 & \text{keep apart}\end{cases}
$$`,
  },
  {
    title: "Hybrid evidence retrieval",
    where: "retrieval.py",
    what: "Bulletin entries and prerequisite syllabi are split into schedule-row passages. Keyword (BM25) and embedding rankings are fused; Gemini judges coverage from the top passages, and code checks its quote.",
    math: String.raw`$$
\mathrm{BM25}(q,d)=\sum_{t\in q}\mathrm{idf}(t)\,\frac{f_{t,d}\,(k_1+1)}{f_{t,d}+k_1\big(1-b+b\,\tfrac{|d|}{\overline{|d|}}\big)}
$$
$$
\mathrm{idf}(t)=\ln\!\Big(1+\frac{N-n_t+0.5}{n_t+0.5}\Big)\qquad \mathrm{RRF}(d)=\sum_{r}\frac{1}{60+\mathrm{rank}_r(d)}
$$
$$
\text{quote accepted} \iff \frac{1}{|Q|}\sum_{t\in Q}[\,t\in P\,]\ \ge\ 0.6
$$`,
    note: "k₁ = 1.4, b = 0.75; RRF fuses the BM25 and embedding rankings. A quote Q counts only if 60% of its words are in the cited passage P.",
  },
  {
    title: "Knowledge space model",
    where: "mastery.py",
    what: "Knowledge Space Theory, the idea behind ALEKS: nobody knows multiple regression without simple regression, so the only possible knowledge states are the prerequisite-closed sets. Every answer updates every state.",
    math: String.raw`$$
\mathcal{K}=\{K\subseteq C:\ c\in K,\ u\to c\ \Rightarrow\ u\in K\}
$$
$$
P(K)\propto\prod_{c\in K}p_c\prod_{c\notin K}(1-p_c)
$$
$$
P(\checkmark\mid c,K)=\begin{cases}1-s & c\in K\\ g & c\notin K\end{cases}
$$
$$
P(K\mid r)\propto P(K)\,P(r\mid K),\qquad P(c)=\sum_{K\ni c}P(K)
$$`,
    note: "Slip s = 0.10, guess g = 0.25. Priors come from what the student says (studied 0.60, not sure 0.40, never 0.08) and from coverage. Ready at 85%, probably known at 60%: one right answer from 50% gives 78%, two give 93%.",
  },
  {
    title: "Adaptive check",
    where: "assessment.py",
    what: "The next question is the one expected to remove the most uncertainty about the concepts needed in the next 3 weeks (and their foundations). The check stops when no question is worth asking.",
    math: String.raw`$$
H(p)=-p\log_2 p-(1-p)\log_2(1-p)
$$
$$
\mathrm{IG}(i)=\sum_{c\in F}H\big(P(c)\big)-\mathbb{E}_{r}\Big[\sum_{c\in F}H\big(P(c\mid r)\big)\Big]
$$`,
    note: "F = concepts needed in the next 3 weeks plus their foundations; r = the answer, right or wrong. The next question maximizes IG; the check stops when the best IG is below 0.02 bits, or after 8 questions.",
  },
  {
    title: "Precedence-aware scheduling",
    where: "readiness.py",
    what: "Every concept the coming classes need and the student doesn't know becomes a task. Deadlines are pulled earlier along the graph so a foundation finishes in time for what builds on it; then tasks fill the weekly budget earliest-deadline-first. Whatever doesn't fit is reported with the shortfall in minutes.",
    math: String.raw`$$
d'(u)=\min\Big(d(u),\ \min_{u\to v}\ d'(v)-\Big\lceil \frac{t(v)}{B/7}\Big\rceil\Big)
$$
$$
\text{capacity}_1 = B\cdot\frac{\text{days left}}{7},\qquad \text{capacity}_{w}=B\ \ (w>1)
$$`,
    note: "d = the date the class needs it (never earlier than today), t = study minutes, B = the student's weekly minutes. Tasks are taken in order of d′ (earliest deadline first).",
  },
];

const RESULTS = [
  ["Recall", "0.92"], ["Precision", "0.79"], ["F1", "0.84"], ["Offline baseline F1", "0.57"],
];

const SHOTS = [
  { src: "/demo/plan.jpg", alt: "A pace plan: a sticky note says to start with a 3-minute check; week 4's items are listed with minutes and due dates.", caption: "The pace plan" },
  { src: "/demo/map.jpg", alt: "The prerequisite map: pinned concept cards in three columns joined by coloured wool strings.", caption: "The prerequisite map" },
  { src: "/demo/check.jpg", alt: "A quick-check question about simple linear regression with four choices.", caption: "The quick check" },
];

/** Steps through the build stages, then the student steps, while the section is on screen. */
function useRunner(total: number, active: boolean): number {
  const [i, setI] = useState(-1);
  useEffect(() => {
    if (!active) return;
    const t = setTimeout(() => setI((x) => (x + 1 >= total + 2 ? -1 : x + 1)), i < 0 ? 600 : i >= total ? 2600 : 1300);
    return () => clearTimeout(t);
  }, [i, total, active]);
  return i;
}

function SampleButton({ children }: { children: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <button className="btn primary" disabled={busy} onClick={async () => {
      setBusy(true);
      const c = await api.sample();
      rememberCourse(c.id);
      go(`/c/${c.id}`);
    }}>{busy ? <Spinner /> : null} {children}</button>
  );
}

export function HowItWorks() {
  const [flowRef, flowSeen] = useInView<HTMLElement>();
  const reduced = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const step = useRunner(BUILD.length + STUDENT.length, flowSeen && !reduced);
  const state = (k: number) => (reduced || step < 0 ? "" : k < step ? " done" : k === step ? " running" : "");
  const now = step >= 0 && step < BUILD.length ? `Stage ${BUILD[step].n} · ${BUILD[step].name}`
    : step >= BUILD.length && step < BUILD.length + STUDENT.length ? `Student · ${STUDENT[step - BUILD.length].name}` : null;
  return (
    <div className="how">
      <section className="how-hero">
        <div className="how-hero-text">
          <h1>From a syllabus to a pace plan, <mark className="hl">with the math shown.</mark></h1>
          <p className="lede">
            Throughline reads an SF State syllabus and the Bulletin, maps the earlier-course knowledge each week assumes,
            checks you in a few questions, and schedules what to review before the class that needs it.
            Gemini reads and proposes; every number you see comes from code you can test.
          </p>
          <div className="row-actions">
            <SampleButton>Try the live demo</SampleButton>
            <a className="btn" href="#algorithms" onClick={(e) => { e.preventDefault(); document.getElementById("algorithms")?.scrollIntoView({ behavior: "smooth" }); }}>See the formulas</a>
          </div>
          <p className="small muted">The demo is a fictional course with a simulated class. It needs no account and no AI.</p>
        </div>
        <section className="sheet taped how-try" aria-labelledby="try-it">
          <div className="sheet-head">
            <h2 id="try-it">Try the student model</h2>
            <span className="muted small">Mark answers; watch the graph carry them</span>
          </div>
          <div className="sheet-body"><KnowledgeDemo /></div>
        </section>
      </section>

      <section className="how-section" aria-labelledby="watch">
        <h2 id="watch">Watch it run</h2>
        <p className="how-sub">A student's path through the app, start to finish. Pause it, or jump to any step.</p>
        <LiveDemo />
      </section>

      <section className="how-section" aria-labelledby="workflow" ref={flowRef}>
        <h2 id="workflow">The workflow</h2>
        <p className="how-sub">Once per course, about two minutes and twenty Gemini calls. Then minutes per student.</p>
        <p className="how-now" aria-hidden>{now ? <><span className="how-dot" /> Running · {now}</> : <span className="muted">Every course goes through these seven stages once.</span>}</p>
        <h3 className="how-lane">Building the course map <span className="muted small">(once per course)</span></h3>
        <ol className="how-flow">
          {BUILD.map((s, k) => (
            <li key={s.n} className={`how-step${state(k)}`}>
              <span className="how-num">{state(k) === " done" ? <Icon name="check" size={13} /> : s.n}</span>
              <i className="how-bar" />
              <h3>{s.name}</h3>
              {s.gemini ? <p><span className="tag who-ai">Gemini</span> {s.gemini}</p> : <p><span className="tag">No model</span></p>}
              <p><span className="tag who-code">Code</span> {s.code}</p>
            </li>
          ))}
        </ol>
        <h3 className="how-lane">Each student <span className="muted small">(a few minutes)</span></h3>
        <ol className="how-flow student">
          {STUDENT.map((s, k) => (
            <li key={s.n} className={`how-step${state(BUILD.length + k)}`}>
              <span className="how-num">{state(BUILD.length + k) === " done" ? <Icon name="check" size={13} /> : s.n}</span>
              <i className="how-bar" />
              <h3>{s.name}</h3>
              <p>{s.text}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="how-section" id="algorithms" aria-labelledby="algorithms-h">
        <h2 id="algorithms-h">The algorithms</h2>
        <p className="how-sub">Each one, with its constants, as it runs in <code>backend/throughline</code>.</p>
        <div className="how-algos">
          {ALGORITHMS.map((a) => (
            <article key={a.title} className="sheet how-algo">
              <div className="sheet-head"><h3>{a.title}</h3><span className="src-tag">{a.where}</span></div>
              <div className="sheet-body">
                <p>{a.what}</p>
                <div className="how-math"><Markdown text={a.math} /></div>
                {a.note && <p className="small muted">{a.note}</p>}
              </div>
            </article>
          ))}
        </div>
        <p className="small muted how-privacy">
          Class view: the owner sees aggregates only, and a concept appears only once 5 or more students have answered (k-anonymity, k = 5).
        </p>
      </section>

      <section className="how-section" aria-labelledby="demo-view">
        <h2 id="demo-view">What a student sees</h2>
        <div className="how-shots">
          {SHOTS.map((s) => (
            <figure key={s.src} className="how-shot">
              <img src={s.src} alt={s.alt} loading="lazy" width={1180} height={750} />
              <figcaption>{s.caption}</figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="how-section how-proof" aria-labelledby="proof">
        <div>
          <h2 id="proof">Measured, not assumed</h2>
          <p className="how-sub">Four real SF State syllabi against hand-written labels, three Gemini mapping runs each.</p>
          <dl className="how-results">
            {RESULTS.map(([k, v]) => <div key={k}><dt className="label">{k}</dt><dd className="stat">{v}</dd></div>)}
          </dl>
        </div>
      </section>

      <section className="how-section" aria-labelledby="built-with">
        <h2 id="built-with">Built with</h2>
        <p className="how-sub">SF Hacks × Google Developer Groups AI Hackathon, Build for SFSU track. The Google stack on top; the rest of the build below.</p>
        <TechCarousel />
      </section>

      <section className="how-cta sticky">
        <h2>See it on a course</h2>
        <div className="row-actions">
          <SampleButton>Open the sample course</SampleButton>
          <a className="btn" href="#/">Add your own course</a>
        </div>
      </section>
    </div>
  );
}

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { Spinner, StatusIcon } from "../components/ui";
import { api, type CourseDetail, type GraphData } from "../lib/api";
import { COVERAGE_LABEL, STATUS_LABEL, pct } from "../lib/format";

type Node = GraphData["nodes"][number];
interface Placed extends Node { x: number; y: number; col: number }

const H = 84;
const NARROW = 560;
const ROW_GAP = 14;
const SLACK = 40; // room below the tallest column, so cards there can move too
const PAD = 12;
const COLUMN_NAMES = ["Start here", "Builds on that", "Then", "Then", "Then", "Then"];

/**
 * Layered drawing of the prerequisite DAG: a concept's column is its longest path from a concept with no
 * prerequisite here, and rows are ordered by the barycenter of their neighbours to keep threads from crossing.
 */
function layout(data: GraphData, width: number) {
  const cols = Math.max(1, ...data.nodes.map((n) => n.depth + 1));
  const gap = width < 640 ? 28 : 56;
  const w = Math.max(150, Math.min(220, (width - PAD * 2 - gap * (cols - 1)) / cols));
  const sec = Math.max(w + gap, (width - PAD * 2) / cols);
  const firstWeek = new Map<string, number>();
  for (const n of data.needs) firstWeek.set(n.concept_id, Math.min(firstWeek.get(n.concept_id) ?? 99, n.week));

  const columns: Node[][] = Array.from({ length: cols }, () => []);
  for (const n of data.nodes) columns[n.depth].push(n);
  for (const col of columns) col.sort((a, b) => (firstWeek.get(a.id) ?? 99) - (firstWeek.get(b.id) ?? 99) || a.name.localeCompare(b.name));

  const preds = new Map<string, string[]>();
  const succs = new Map<string, string[]>();
  for (const e of data.edges) {
    preds.set(e.dst, [...(preds.get(e.dst) ?? []), e.src]);
    succs.set(e.src, [...(succs.get(e.src) ?? []), e.dst]);
  }
  const row = new Map<string, number>();
  const index = () => columns.forEach((col) => col.forEach((n, i) => row.set(n.id, i)));
  const sortBy = (col: Node[], nbrs: Map<string, string[]>) => {
    const key = (n: Node) => {
      const ys = (nbrs.get(n.id) ?? []).map((m) => row.get(m)).filter((v): v is number => v != null);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : (row.get(n.id) ?? 0);
    };
    col.sort((a, b) => key(a) - key(b));
  };
  index();
  for (let pass = 0; pass < 3; pass++) {
    for (let c = 1; c < cols; c++) { sortBy(columns[c], preds); index(); }
    for (let c = cols - 2; c >= 0; c--) { sortBy(columns[c], succs); index(); }
  }

  const tallest = Math.max(...columns.map((c) => c.length), 1);
  const placed = new Map<string, Placed>();
  columns.forEach((col, c) => {
    const offset = ((tallest - col.length) * (H + ROW_GAP)) / 2;
    col.forEach((n, i) => placed.set(n.id, { ...n, col: c, x: PAD + c * sec + (sec - w) / 2, y: PAD + 26 + offset + i * (H + ROW_GAP) }));
  });
  return { placed, w, sec, cols, width: PAD * 2 + cols * sec, height: PAD * 2 + 26 + tallest * (H + ROW_GAP) - ROW_GAP + SLACK };
}

/** A small, stable tilt per card, so pinned cards look hand-placed but never move between renders. */
function tilt(id: string): string {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return `${((Math.abs(h) % 7) - 3) * 0.12}deg`;
}

/**
 * A wool string pulled between two pins. It hangs with a slight sag, more for longer strings, like real
 * string on a board. Direction comes from the columns (left to right), not from arrowheads.
 */
function string(x1: number, y1: number, x2: number, y2: number) {
  const sag = Math.min(18, 5 + Math.hypot(x2 - x1, y2 - y1) * 0.04);
  return `M${x1},${y1} Q${(x1 + x2) / 2},${(y1 + y2) / 2 + sag} ${x2},${y2}`;
}

/**
 * Where a card's pin goes. Strings are drawn over the cards, so by default the pin sits on the side its
 * strings leave from (top right) or arrive at (top left), in the strip above the text. A pin the student has
 * moved stays where they put it on the card.
 */
function pinAt(n: Placed, w: number, out: Set<string>, into: Set<string>, spot?: Spot) {
  if (spot?.px != null && spot.py != null) return { x: n.x + spot.px * w, y: n.y + spot.py * H };
  const dx = out.has(n.id) && !into.has(n.id) ? w - 12 : into.has(n.id) && !out.has(n.id) ? 24 : w / 2 + 6;
  return { x: n.x + dx, y: n.y + 18 }; // where the needle goes in; the head sits up and to the left
}

/**
 * What a student rearranged: where a card sits inside its section (fx, fy) and where its pin sits on the card
 * (px, py), all as fractions so they survive a resize. Remembered per viewer, per course.
 */
type Spot = { fx?: number; fy?: number; px?: number; py?: number };
const spotsKey = (courseId: string) => `throughline:map:${courseId}`;
function loadSpots(courseId: string): Record<string, Spot> {
  try { return JSON.parse(localStorage.getItem(spotsKey(courseId)) ?? "{}") as Record<string, Spot>; } catch { return {}; }
}
function saveSpots(courseId: string, spots: Record<string, Spot>) {
  try {
    if (Object.keys(spots).length) localStorage.setItem(spotsKey(courseId), JSON.stringify(spots));
    else localStorage.removeItem(spotsKey(courseId));
  } catch { /* storage blocked: positions just won't be remembered */ }
}
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** A press on a card or pin. `armed` once it may move: at once for a mouse, after HOLD_MS for a finger. */
type Drag = { id: string; px: number; py: number; x: number; y: number; moved: boolean; touch: boolean; armed: boolean; timer?: number };
const HOLD_MS = 350;

function when(n: Node): string {
  const need = n.next_need;
  if (!need) return n.foundation ? "Foundation" : "No upcoming use";
  if (need.overdue) return "In use now";
  if (need.via) return `For ${need.via}`;
  return need.week > 0 ? `Week ${need.week}` : "Assessment";
}

export function PrereqMapTab({ course }: { course: CourseDetail }) {
  const { data, isLoading } = useQuery({ queryKey: ["graph", course.id], queryFn: () => api.graph(course.id) });
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const [focus, setFocus] = useState<string | null>(null);
  const [spots, setSpots] = useState<Record<string, Spot>>(() => loadSpots(course.id));
  const [dragging, setDragging] = useState<string | null>(null);
  const [raised, setRaised] = useState<string | null>(null); // the card moved last stays on top
  const drag = useRef<Drag | null>(null);
  const swallowClick = useRef(false);

  useEffect(() => { if (!dragging) saveSpots(course.id, spots); }, [dragging, spots, course.id]);

  // Touch: once a card or pin is held, the finger moves it instead of scrolling the page.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const hold = (e: TouchEvent) => { if (drag.current?.armed) e.preventDefault(); };
    el.addEventListener("touchmove", hold, { passive: false });
    return () => el.removeEventListener("touchmove", hold);
  }, [data]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);

  const g = useMemo(() => (data ? layout(data, width) : null), [data, width]);

  const lit = useMemo(() => {
    if (!data || !focus) return null;
    const keep = new Set([focus]);
    const walk = (from: string, dir: "up" | "down") => {
      for (const e of data.edges) {
        const [a, b] = dir === "up" ? [e.dst, e.src] : [e.src, e.dst];
        if (a === from && !keep.has(b)) { keep.add(b); walk(b, dir); }
      }
    };
    walk(focus, "up");
    walk(focus, "down");
    return keep;
  }, [data, focus]);

  if (isLoading || !data || !g) return <section className="sheet"><div className="empty"><Spinner /></div></section>;
  const names = new Map(data.nodes.map((n) => [n.id, n.name]));
  const order = new Map(data.nodes.map((n, i) => [n.id, i]));
  const out = new Set(data.edges.map((e) => e.src));
  // Invisible section borders: a card stays inside its own column, between the column label and the bottom.
  const top = PAD + 26, bottom = g.height - PAD - H;
  const bounds = (n: Placed) => { const left = PAD + n.col * g.sec + 6; return { left, right: Math.max(left, left + g.sec - 12 - g.w) }; };
  const at = (n: Placed): Placed => {
    const s = spots[n.id];
    if (s?.fx == null || s.fy == null) return n;
    const b = bounds(n);
    return { ...n, x: b.left + s.fx * (b.right - b.left), y: top + s.fy * Math.max(0, bottom - top) };
  };
  const pos = new Map([...g.placed.values()].map((n) => [n.id, at(n)]));
  const place = (n: Placed, x: number, y: number) => {
    const b = bounds(n);
    const fx = b.right > b.left ? (clamp(x, b.left, b.right) - b.left) / (b.right - b.left) : 0.5;
    const fy = bottom > top ? (clamp(y, top, bottom) - top) / (bottom - top) : 0;
    setSpots((s) => ({ ...s, [n.id]: { ...s[n.id], fx, fy } }));
  };
  const placePin = (n: Placed, x: number, y: number) => {
    const px = clamp((x - n.x) / g.w, 16 / g.w, 1 - 6 / g.w), py = clamp((y - n.y) / H, 19 / H, 1 - 4 / H);
    setSpots((s) => ({ ...s, [n.id]: { ...s[n.id], px, py } }));
  };
  /**
   * Press and drag. A mouse drags as soon as it moves; a finger has to hold still for a moment first, so a swipe
   * that starts on a card still scrolls the page and a quick tap still opens the concept.
   */
  const begin = (e: ReactPointerEvent<Element>, id: string, x: number, y: number) => {
    if (e.button !== 0) return;
    const touch = e.pointerType !== "mouse";
    const d: Drag = { id, px: e.clientX, py: e.clientY, x, y, moved: false, touch, armed: !touch };
    drag.current = d;
    const el = e.currentTarget, pointer = e.pointerId;
    if (!touch) el.setPointerCapture(pointer);
    else d.timer = window.setTimeout(() => {
      if (drag.current !== d) return;
      d.armed = true;
      try { el.setPointerCapture(pointer); } catch { /* pointer already gone */ }
      setDragging(id);
      if (!id.startsWith("pin:")) setRaised(id);
    }, HOLD_MS);
  };
  const follow = (e: ReactPointerEvent<Element>, id: string, move: (dx: number, dy: number) => void) => {
    const d = drag.current;
    if (!d || d.id !== id) return;
    const dx = e.clientX - d.px, dy = e.clientY - d.py;
    if (!d.armed) {
      if (Math.hypot(dx, dy) > 8) { clearTimeout(d.timer); drag.current = null; } // a swipe: let the page scroll
      return;
    }
    if (!d.moved && !d.touch && Math.hypot(dx, dy) < 5) return;
    if (!d.moved) { d.moved = true; setDragging(id); if (!id.startsWith("pin:")) setRaised(id); }
    move(dx, dy);
  };
  const endDrag = () => {
    const d = drag.current;
    drag.current = null;
    if (d) clearTimeout(d.timer);
    setDragging(null);
    if (d?.moved || (d?.touch && d.armed)) { swallowClick.current = true; setTimeout(() => { swallowClick.current = false; }, 0); }
  };
  const into = new Set(data.edges.map((e) => e.dst));

  return (
    <section className="sheet taped">
      <div className="sheet-head">
        <h2>Prerequisite map</h2>
        <span className="muted small">
          {data.nodes.length} concepts · {data.edges.length} "builds on" links · strings run from what you need first (left) to what builds on it (right)
          {width < NARROW ? <> · swipe in any direction to explore; hold a card to move it</> : <> · drag a card to rearrange its column</>}
          {Object.keys(spots).length > 0 && <> · <button className="btn ghost small inline-btn" onClick={() => setSpots({})}>Reset layout</button></>}
        </span>
      </div>
      <div className="sheet-body">
        {data.edges.length === 0 && (
          <p className="small muted">No concept here builds on another, so they can be studied in any order. The plan orders them by when the course needs them.</p>
        )}
        {/* On phones the board sits in a window that pans both ways, like a map; elsewhere the page scrolls it. */}
        <div className={`graph-wrap ${width < NARROW ? "pan" : ""}`} ref={box}>
          <div className="graph" style={{ width: g.width, height: g.height }}>
            {Array.from({ length: g.cols }, (_, c) => (
              <span key={c} className="graph-col label" style={{ left: PAD + c * g.sec, width: g.sec }}>{COLUMN_NAMES[c] ?? "Then"}</span>
            ))}
            {dragging && pos.has(dragging) && (() => {
              const n = pos.get(dragging)!;
              return <span className="section-area" style={{ left: PAD + n.col * g.sec, width: g.sec, top: top - 6, height: bottom - top + H + 12 }} />;
            })()}
            {[...pos.values()].map((n) => (
              <a key={n.id} href={`#/c/${course.id}/k/${n.id}`} draggable={false}
                 className={`gnode st-${n.status} cov-${n.coverage} ${lit && !lit.has(n.id) ? "dim" : ""} ${focus === n.id ? "focus" : ""} ${dragging === n.id ? "dragging" : ""} ${raised === n.id ? "raised" : ""}`}
                 onPointerDown={(e) => begin(e, n.id, n.x, n.y)}
                 onPointerMove={(e) => follow(e, n.id, (dx, dy) => place(n, drag.current!.x + dx, drag.current!.y + dy))}
                 onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}
                 onContextMenu={(e) => e.preventDefault()}
                 onClick={(e) => { if (swallowClick.current) { e.preventDefault(); swallowClick.current = false; } }}
                 onKeyDown={(e) => {
                   const step = e.shiftKey ? 40 : 10;
                   const move = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
                   if (!move) return;
                   e.preventDefault();
                   if (e.altKey) { const p = pinAt(n, g.w, out, into, spots[n.id]); placePin(n, p.x + move[0] / 2, p.y + move[1] / 2); } // Alt: move the pin
                   else place(n, n.x + move[0], n.y + move[1]);
                 }}
                 style={{ left: n.x, top: n.y, width: g.w, height: H, "--tilt": tilt(n.id) } as CSSProperties}
                 onMouseEnter={() => setFocus(n.id)} onMouseLeave={() => setFocus(null)} onFocus={() => setFocus(n.id)} onBlur={() => setFocus(null)}
                 title={`${n.name}: ${STATUS_LABEL[n.status]} (${pct(n.p)}). ${COVERAGE_LABEL[n.coverage].hint} Drag, or use the arrow keys, to move it within its column; Alt + arrow keys move its pin.`}>
                <span className="gn-top">
                  <span className={`status ${n.status}`}><StatusIcon status={n.status} size={13} /></span>
                  <b>{n.name}</b>
                </span>
                <span className="gn-bottom">
                  <span className={n.next_need?.overdue ? "late" : ""}>{when(n)}</span>
                  <span className="mono">{pct(n.p)}</span>
                </span>
                <span className="gn-p"><i style={{ width: `${Math.max(3, n.p * 100)}%` }} /></span>
              </a>
            ))}
            <svg className="board" width={g.width} height={g.height} aria-hidden>
              <defs>
                <filter id="wool" x="-5%" y="-20%" width="110%" height="140%">
                  <feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="3" result="fuzz" />
                  <feDisplacementMap in="SourceGraphic" in2="fuzz" scale="2.2" xChannelSelector="R" yChannelSelector="G" result="yarn" />
                  <feDropShadow in="yarn" dx="1.5" dy="2.5" stdDeviation="1.2" floodColor="#000" floodOpacity="0.28" />
                </filter>
                <linearGradient id="steel" x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor="#f4f6f7" />
                  <stop offset="0.5" stopColor="#a3aab1" />
                  <stop offset="1" stopColor="#575e65" />
                </linearGradient>
              </defs>
              {data.edges.map((e) => {
                const a = pos.get(e.src);
                const b = pos.get(e.dst);
                if (!a || !b) return null;
                const p1 = pinAt(a, g.w, out, into, spots[a.id]), p2 = pinAt(b, g.w, out, into, spots[b.id]);
                const d = string(p1.x, p1.y, p2.x, p2.y);
                const on = !lit || (lit.has(e.src) && lit.has(e.dst));
                const color = `var(--c${(order.get(e.src) ?? 0) % 8 + 1})`;
                return (
                  <g key={`${e.src}-${e.dst}`} className={`thread ${on ? (lit ? "lit" : "") : "dim"} ${e.confidence < 0.67 ? "weak" : ""}`}
                     style={{ "--t": color } as CSSProperties} filter="url(#wool)">
                    <path className="fuzz" d={d} />
                    <path className="yarn" d={d} />
                    <path className="ply" d={d} />
                    <path className="shine" d={d} />
                  </g>
                );
              })}
              {[...pos.values()].map((n) => {
                const p = pinAt(n, g.w, out, into, spots[n.id]);
                return (
                  <g key={n.id} className={`pin cov-${n.coverage} ${lit && !lit.has(n.id) ? "dim" : ""} ${dragging === `pin:${n.id}` ? "dragging" : ""}`}
                     transform={`translate(${p.x} ${p.y})`}
                     onPointerDown={(e) => { e.stopPropagation(); begin(e, `pin:${n.id}`, p.x, p.y); }}
                     onPointerMove={(e) => follow(e, `pin:${n.id}`, (dx, dy) => placePin(n, drag.current!.x + dx, drag.current!.y + dy))}
                     onPointerUp={endDrag} onPointerCancel={endDrag} onLostPointerCapture={endDrag}
                     onContextMenu={(e) => e.preventDefault()}>
                    <title>{`${n.name}: drag the pin to move where its strings are tied`}</title>
                    <circle className="pin-hit" cx={-5} cy={-8} r={12} />
                    <polygon className="pin-shadow" points="-4.6,-8.4 -1.8,-10 2.4,1.6" />
                    <ellipse className="pin-shadow" cx={-3} cy={-8.5} rx={6} ry={4.6} />
                    <polygon className="pin-needle" points="-9,-10.6 -5.4,-13 0.4,0.6" fill="url(#steel)" />
                    <circle className="pin-head" cx={-8} cy={-13} r={6.5} />
                    <circle className="pin-shine" cx={-10.2} cy={-15.4} r={2} />
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
        {(() => {
          const key = <div className="legend">
          {(["ready", "likely", "refresh", "learn", "unchecked"] as const).map((s) => (
            <span key={s} className="item"><span className={`status ${s}`}><StatusIcon status={s} size={12} /></span>{STATUS_LABEL[s]}</span>
          ))}
          <span className="item">Pin colour:</span>
          <span className="item"><span className="swatch cov-listed" /> taught in a listed prerequisite</span>
          <span className="item"><span className="swatch cov-likely" /> probably from a listed prerequisite</span>
          <span className="item"><span className="swatch cov-missing" /> not in listed prerequisites</span>
          <span className="item"><span className="swatch cov-unknown" /> not confirmed</span>
          <span className="item"><svg className="thread-sample" width="30" height="8" aria-hidden><g className="thread weak" style={{ "--t": "var(--ink-3)" } as CSSProperties}><path className="yarn" d="M2 4h26" /></g></svg> dashed string: fewer than 2 of 3 mapping runs agreed</span>
</div>;
          return width < NARROW ? <details className="legend-key"><summary>What the icons and pin colours mean</summary>{key}</details> : key;
        })()}
        <details className="graph-list">
          <summary className="small">Show as a list</summary>
          <ul className="plain">
            {[...g.placed.values()].sort((a, b) => a.col - b.col || a.y - b.y).map((n) => {
              const before = data.edges.filter((e) => e.dst === n.id).map((e) => names.get(e.src));
              return (
                <li key={n.id}>
                  <a href={`#/c/${course.id}/k/${n.id}`}>{n.name}</a> · {STATUS_LABEL[n.status]} ({pct(n.p)}) · {when(n)}
                  {before.length > 0 && <span className="muted"> · builds on {before.join(", ")}</span>}
                </li>
              );
            })}
          </ul>
        </details>
      </div>
    </section>
  );
}

import { LOGOS, type LogoName } from "../lib/logos";

type Item = { name: string; logo?: LogoName; note?: string };

const GOOGLE: Item[] = [
  { name: "Gemini 3.5 Flash", logo: "googlegemini" },
  { name: "Gemini embeddings", logo: "googlegemini" },
  { name: "Cloud Run", logo: "googlecloud" },
  { name: "Firestore", logo: "firebase" },
  { name: "Cloud Tasks", logo: "googlecloud" },
  { name: "Firebase Authentication", logo: "firebase" },
  { name: "Secret Manager", logo: "googlecloud" },
  { name: "Cloud Build", logo: "googlecloud" },
  { name: "Artifact Registry", logo: "googlecloud" },
  { name: "Vertex AI", logo: "googlecloud" },
  { name: "Cloud Logging & Monitoring", logo: "googlecloud" },
];

const BUILD: Item[] = [
  { name: "SF Hacks", note: "Organizer" },
  { name: "Google Developer Groups", logo: "google", note: "Organizer" },
  { name: "SFSU AI Student Commons", note: "Host" },
  { name: "React", logo: "react" },
  { name: "TypeScript", logo: "typescript" },
  { name: "Vite", logo: "vite" },
  { name: "TanStack Query", logo: "tanstack" },
  { name: "Python", logo: "python" },
  { name: "FastAPI", logo: "fastapi" },
  { name: "Pydantic", logo: "pydantic" },
  { name: "NumPy", logo: "numpy" },
  { name: "Docker", logo: "docker" },
  { name: "GitHub Actions", logo: "githubactions" },
  { name: "Claude Code", logo: "claude", note: "Built with" },
];

/** Very dark or very light brand colours would vanish on one of the themes; those marks take the ink colour. */
function tone(hex: string): string | undefined {
  const n = parseInt(hex.slice(1), 16);
  const lum = (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
  return lum < 0.3 || lum > 0.8 ? undefined : hex;
}

function Chip({ item, dup = false }: { item: Item; dup?: boolean }) {
  const logo = item.logo ? LOGOS[item.logo] : null;
  return (
    <li className="tc-chip" aria-hidden={dup || undefined}>
      {logo ? (
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden style={{ color: tone(logo.hex) }}><path d={logo.path} fill="currentColor" /></svg>
      ) : <span className="tc-mono" aria-hidden>{item.name.split(" ").map((w) => w[0]).slice(0, 2).join("")}</span>}
      <span className="tc-name">{item.name}</span>
      {item.note && <span className="tc-note">{item.note}</span>}
    </li>
  );
}

function Row({ items, reverse, label }: { items: Item[]; reverse?: boolean; label: string }) {
  return (
    <div className="tc-row" role="group" aria-label={label}>
      <ul className={`tc-track${reverse ? " reverse" : ""}`}>
        {items.map((it) => <Chip key={it.name} item={it} />)}
        {items.map((it) => <Chip key={`dup-${it.name}`} item={it} dup />)}
      </ul>
    </div>
  );
}

/** Two looping rows of stickers: the Google stack, then the hackathon and the rest of the build. */
export function TechCarousel() {
  return (
    <div className="tc">
      <Row items={GOOGLE} label="Google technologies" />
      <Row items={BUILD} reverse label="The hackathon and the rest of the build" />
    </div>
  );
}

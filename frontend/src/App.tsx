import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Wordmark } from "./components/ui";
import { signInWithGoogle, signOut } from "./lib/session";
import { useAccount } from "./lib/useAccount";
import { CoursePage } from "./pages/CoursePage";
import { HowItWorks } from "./pages/HowItWorks";
import { JoinRedirect, Welcome } from "./pages/Welcome";

type Theme = "system" | "light" | "dark";

export type RouteState =
  | { page: "home" }
  | { page: "how" }
  | { page: "join"; code: string }
  | { page: "course"; id: string; tab: string; concept?: string };

// A concept opens as a drawer over whichever course tab you were on, and closing it goes back there.
let lastTab = { id: "", tab: "plan" };

export function parseHash(hash: string): RouteState {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "how") return { page: "how" };
  if (parts[0] === "j" && parts[1]) return { page: "join", code: parts[1] };
  if (parts[0] === "c" && parts[1]) {
    if (parts[2] === "k" && parts[3]) return { page: "course", id: parts[1], tab: lastTab.id === parts[1] ? lastTab.tab : "plan", concept: parts[3] };
    lastTab = { id: parts[1], tab: parts[2] || "plan" };
    return { page: "course", id: parts[1], tab: lastTab.tab };
  }
  return { page: "home" };
}

export function go(path: string) {
  window.location.hash = path;
}

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("theme") as Theme) || "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("theme", theme);
    } catch {
      /* storage may be unavailable */
    }
  }, [theme]);
  const next = () => setTheme((t) => (t === "system" ? "light" : t === "light" ? "dark" : "system"));
  return [theme, next];
}

function AccountControl() {
  const a = useAccount();
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const prev = useRef<string | null>(null);
  // A different account sees different courses and answers: refetch everything.
  useEffect(() => {
    const key = `${a.signedIn}:${a.email}`;
    if (prev.current !== null && prev.current !== key) qc.invalidateQueries();
    prev.current = key;
  }, [a.signedIn, a.email, qc]);
  if (!a.loaded || a.mode !== "firebase") return null;
  if (a.signedIn) {
    return (
      <span className="account">
        <span className="muted small" title={a.email ?? ""}>{a.name || a.email}</span>
        <button className="btn ghost small" onClick={() => signOut()}>Sign out</button>
      </span>
    );
  }
  return (
    <span className="account">
      {error && <span className="error-text small">{error}</span>}
      <button className="btn small" onClick={() => signInWithGoogle().catch((e) => setError((e as Error).message))}>Sign in with Google</button>
    </span>
  );
}

export default function App() {
  const [route, setRoute] = useState<RouteState>(() => parseHash(window.location.hash));
  const [theme, cycleTheme] = useTheme();

  useEffect(() => {
    const onHash = () => {
      setRoute(parseHash(window.location.hash));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return (
    <div className="shell">
      <header className="topbar">
        <a className="wordmark" href="#/">
          <Wordmark size={34} />
          <div>
            <strong>Throughline</strong>
            <span>Keep pace with the prerequisites your class assumes</span>
          </div>
        </a>
        <span className="spacer" />
        <a className={`how-link${route.page === "how" ? " on" : ""}`} href="#/how" aria-current={route.page === "how" ? "page" : undefined}>How it works</a>
        <AccountControl />
        <button className="theme-toggle" onClick={cycleTheme} aria-label="Change color theme">
          <svg className="tt-icon" width="18" height="18" viewBox="0 0 16 16" aria-hidden><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.6" /><path d="M8 2a6 6 0 0 1 0 12z" fill="currentColor" /></svg>
          <span className="tt-text"><span className="tt-label">Theme: </span>{theme}</span>
        </button>
      </header>
      <main>
        {route.page === "home" && <Welcome />}
        {route.page === "how" && <HowItWorks />}
        {route.page === "join" && <JoinRedirect code={route.code} />}
        {route.page === "course" && <CoursePage key={route.id} id={route.id} tab={route.tab} concept={route.concept} />}
      </main>
      <footer className="foot muted">
        Student project for SF Hacks 2026. Not affiliated with or endorsed by SF State. Course prerequisites shown from the SF State Bulletin; free textbooks from OpenStax and other open publishers.
      </footer>
    </div>
  );
}

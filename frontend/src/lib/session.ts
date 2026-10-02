/**
 * Who the browser is. The server's /api/config decides the mode:
 * - demo: an anonymous id kept in local storage (local development).
 * - firebase: Firebase Authentication. Visitors are signed in anonymously at once (joining a class by QR needs
 *   no account); "Sign in with Google" upgrades that same account, so anything already done stays theirs.
 * The Firebase SDK is loaded only in firebase mode.
 */
import type { Auth, User } from "firebase/auth";

export interface Account {
  mode: "demo" | "firebase";
  signedIn: boolean; // a Google account, not an anonymous visitor
  email: string | null;
  name: string | null;
}

interface ClientConfig {
  auth: "demo" | "firebase";
  firebase?: { apiKey: string; authDomain: string; projectId: string; appId: string };
}

let auth: Auth | null = null;
let mode: Account["mode"] = "demo";
const listeners = new Set<(a: Account) => void>();
let current: Account = { mode: "demo", signedIn: true, email: null, name: null };

function publish(user: User | null) {
  current = { mode, signedIn: !!user && !user.isAnonymous, email: user?.email ?? null, name: user?.displayName ?? null };
  listeners.forEach((fn) => fn(current));
}

/** Resolves once the browser has an identity to send. */
export const ready: Promise<void> = (async () => {
  const res = await fetch("/api/config");
  const cfg: ClientConfig = res.ok ? await res.json() : { auth: "demo" };
  if (cfg.auth !== "firebase" || !cfg.firebase) return;
  mode = "firebase";
  const [{ initializeApp }, fa] = await Promise.all([import("firebase/app"), import("firebase/auth")]);
  auth = fa.getAuth(initializeApp(cfg.firebase));
  await fa.setPersistence(auth, fa.browserLocalPersistence);
  await new Promise<void>((resolve) => {
    const stop = fa.onAuthStateChanged(auth!, async (user) => {
      if (!user) {
        await fa.signInAnonymously(auth!); // fires the listener again with the new user
        return;
      }
      publish(user);
      stop();
      resolve();
    });
  });
  fa.onAuthStateChanged(auth, (user) => user && publish(user));
})();

export function account(): Account {
  return current;
}

export function onAccount(fn: (a: Account) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Headers that identify this browser to the API. */
export async function identityHeaders(demoUid: () => string): Promise<Record<string, string>> {
  await ready;
  if (mode === "firebase" && auth?.currentUser) return { Authorization: `Bearer ${await auth.currentUser.getIdToken()}` };
  return { "X-Demo-User": demoUid() };
}

export async function signInWithGoogle(): Promise<void> {
  await ready;
  if (!auth) return;
  const fa = await import("firebase/auth");
  const provider = new fa.GoogleAuthProvider();
  provider.setCustomParameters({ prompt: "select_account" });
  const user = auth.currentUser;
  if (user?.isAnonymous) {
    try {
      await fa.linkWithPopup(user, provider); // same uid: courses and answers carry over
      await user.reload();
      publish(auth.currentUser);
      return;
    } catch (e) {
      // This Google account already exists here: switch to it (its own courses and answers).
      if ((e as { code?: string }).code !== "auth/credential-already-in-use") throw e;
    }
  }
  await fa.signInWithPopup(auth, provider);
}

export async function signOut(): Promise<void> {
  if (!auth) return;
  const fa = await import("firebase/auth");
  await fa.signOut(auth);
  await fa.signInAnonymously(auth);
}

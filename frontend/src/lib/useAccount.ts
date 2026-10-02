import { useEffect, useState } from "react";
import { account, onAccount, ready, type Account } from "./session";

/** The current account; re-renders on sign-in and sign-out. `loaded` turns true once identity is known. */
export function useAccount(): Account & { loaded: boolean } {
  const [a, setA] = useState(account());
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let live = true;
    ready.then(() => { if (live) { setA(account()); setLoaded(true); } }, () => live && setLoaded(true));
    const stop = onAccount(setA);
    return () => { live = false; stop(); };
  }, []);
  return { ...a, loaded };
}

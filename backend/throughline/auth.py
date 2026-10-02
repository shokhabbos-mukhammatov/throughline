"""Who is calling.

demo mode: an anonymous id the browser keeps in local storage (X-Demo-User). Fine for local runs and tests.
firebase mode: a Firebase ID token (Authorization: Bearer ...). Students who join by link or QR are signed in
anonymously by Firebase, with no friction; adding a course costs model calls, so it needs Google sign-in.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .config import Settings

_CERTS_TTL = 3600


@dataclass(frozen=True)
class Identity:
    uid: str
    signed_in: bool  # a real account (Google), not an anonymous visitor
    email: str = ""


class _CachingRequest:
    """google-auth transport that caches Google's public signing certificates instead of fetching them per call."""

    def __init__(self):
        from google.auth.transport import requests as g_requests

        self._inner = g_requests.Request()
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def __call__(self, url, method="GET", **kwargs):
        if method != "GET":
            return self._inner(url, method=method, **kwargs)
        with self._lock:
            hit = self._cache.get(url)
            if hit and time.time() - hit[0] < _CERTS_TTL:
                return hit[1]
        resp = self._inner(url, method=method, **kwargs)
        if getattr(resp, "status", 500) == 200:
            with self._lock:
                self._cache[url] = (time.time(), resp)
        return resp


_transport: _CachingRequest | None = None


def _verify_firebase(token: str, project: str) -> dict:
    global _transport
    from google.oauth2 import id_token

    if _transport is None:
        _transport = _CachingRequest()
    return id_token.verify_firebase_token(token, _transport, audience=project)


def identify(request: Request, settings: Settings, verifier=None) -> Identity:
    if settings.auth_mode == "firebase":
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(401, "Sign in required")
        try:
            claims = (verifier or _verify_firebase)(header[7:], settings.gcp_project)
        except Exception as exc:  # expired, wrong project, bad signature
            raise HTTPException(401, "Your sign-in expired. Reload the page.") from exc
        provider = (claims.get("firebase") or {}).get("sign_in_provider", "")
        email = (claims.get("email") or "").lower() if claims.get("email_verified") else ""
        return Identity(uid=claims["sub"], signed_in=provider not in ("", "anonymous"), email=email)
    uid = (request.headers.get("X-Demo-User") or "").strip()[:64]
    if not uid:
        raise HTTPException(401, "Missing X-Demo-User header")
    return Identity(uid=uid, signed_in=True)


def require_account(who: Identity, settings: Settings) -> None:
    """Adding a course spends model calls: require a real Google account, optionally from allowed domains."""
    if not who.signed_in:
        raise HTTPException(401, "Sign in with Google to add a course.")
    if settings.auth_mode == "firebase" and settings.allowed_email_domains:
        domain = who.email.rsplit("@", 1)[-1] if "@" in who.email else ""
        if domain not in settings.allowed_email_domains:
            raise HTTPException(403, "Adding courses is limited to " + ", ".join("@" + d for d in settings.allowed_email_domains) + " accounts.")

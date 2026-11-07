"""Authentication for the local Drix API.

Two credentials are accepted:

* ``X-Drix-Key`` header -- intended for scripts, the terminal client and
  the desktop GUI.
* ``drix_session`` HttpOnly cookie -- set by ``GET /`` so the browser never
  needs the key in JavaScript.  Cookie-authenticated calls are additionally
  protected against CSRF by requiring a same-origin ``Sec-Fetch-Site`` (or a
  matching ``Origin``/``Referer``).
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import JSONResponse

from core import logs

COOKIE_NAME = "drix_session"
_SAFE_FETCH_SITES = {"same-origin", "none"}


def _same_origin(request: Request) -> bool:
    """Best-effort CSRF check for cookie-authenticated browsers.

    ``SameSite=Strict`` already stops the cookie from being attached to
    cross-site requests; this adds a second barrier for browsers that send
    ``Sec-Fetch-Site``/``Origin``.  Requests without those headers are
    non-browser clients (or privacy tooling) and are allowed through.
    """
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site:
        return site in _SAFE_FETCH_SITES

    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return True
    try:
        from urllib.parse import urlparse

        parsed = urlparse(origin)
        return (parsed.hostname or "") == (request.url.hostname or "")
    except Exception:
        return False


def _const_eq(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class AuthMiddleware:
    def __init__(self, api_key: str = "", rate_limit: int = 60,
                 protected_prefixes=("/api", "/ia_system/", "/.cache/"),
                 chat_rate_limit: int = 30):
        self.api_key = api_key
        self.rate_limit = rate_limit
        self.chat_rate_limit = chat_rate_limit
        self.protected = tuple(p if p.endswith("/") else p + "/" for p in protected_prefixes)
        self._requests: dict[str, list[float]] = defaultdict(list)

    def _is_protected(self, path: str) -> bool:
        p = path.rstrip("/") + "/"
        return any(p.startswith(prefix) for prefix in self.protected)

    def _rate_limited(self, ip: str, path: str) -> bool:
        # The UI polls runtime status every second; it is lightweight and must
        # never be throttled or the page would think the service had stopped.
        if path.rstrip("/") == "/api/runtime":
            return False
        limit = self.chat_rate_limit if path.rstrip("/") == "/api/chat" else self.rate_limit
        if limit <= 0:
            return False
        now = time.time()
        stamps = [t for t in self._requests[ip] if now - t < 60]
        self._requests[ip] = stamps
        if len(stamps) >= limit:
            return True
        stamps.append(now)
        return False

    def _authenticate(self, request: Request) -> tuple[bool, str]:
        header = request.headers.get("X-Drix-Key", "")
        if header and _const_eq(header, self.api_key):
            return True, "header"

        cookie = request.cookies.get(COOKIE_NAME, "")
        if cookie:
            if not _same_origin(request):
                return False, "cookie-csrf"
            if _const_eq(cookie, self.api_key):
                return True, "cookie"
            return False, "cookie-invalid"

        return False, "none" if not header else "header-invalid"

    async def __call__(self, request: Request, call_next):
        path = request.url.path
        if not self._is_protected(path):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"

        if self.api_key:
            ok, method = self._authenticate(request)
            if not ok:
                reason = "missing or invalid credentials"
                if method == "cookie-csrf":
                    reason = "cross-origin cookie request blocked"
                    logs.warn(f"API CSRF blocked {request.method} {path} ip={ip}")
                else:
                    logs.warn(f"API unauthorized {request.method} {path} ip={ip}")
                return JSONResponse({"detail": "Unauthorized", "reason": reason}, status_code=401)

        if self._rate_limited(ip, path):
            logs.warn(f"API rate-limited {request.method} {path} ip={ip}")
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

        resp = await call_next(request)
        if path.rstrip("/") != "/api/runtime":
            logs.info(f"API {request.method} {path} -> {resp.status_code} ip={ip}")
        return resp

"""FastAPI web application for Drix."""

from __future__ import annotations

import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OLLAMA_MODELS", str(Path(__file__).resolve().parent.parent / "ia_system" / "models"))

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.auth import AuthMiddleware, COOKIE_NAME
from api.routes import router
from core import runtime, secrets

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"


def _resolve_env_in_str(value):
    if not isinstance(value, str):
        return value
    import re
    def repl(m):
        return os.environ.get(m.group(1) or m.group(2) or m.group(3), "")
    return re.sub(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}|\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", repl, value)


def _resolve_security_api_key(cfg: dict) -> str:
    # 1) Environment variable (recommended)
    env_key = os.environ.get("DRIX_SECURITY_API_KEY", "").strip()
    if env_key:
        return env_key
    # 2) Secrets store (hidden/protected local file)
    stored = secrets.get_secret("security:api_key")
    if secrets.is_real_secret(stored):
        return stored.strip()
    # 3) Config value (supports {env:VAR}; plaintext is legacy/migrated away)
    raw = str((cfg.get("security") or {}).get("api_key", "") or "").strip()
    resolved = _resolve_env_in_str(raw).strip()
    if secrets.is_real_secret(resolved) and not resolved.startswith("{env:"):
        # Migrate plaintext legacy key to secrets store, do not keep in config.yaml
        try:
            secrets.set_secret("security:api_key", resolved)
            cfg.setdefault("security", {})["api_key"] = ""
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        except Exception:
            pass
        return resolved
    # 4) Generate and store in secrets store (not config.yaml)
    api_key = secrets.token_hex(32)
    try:
        secrets.set_secret("security:api_key", api_key)
    except Exception:
        pass
    return api_key


with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    _raw_config = yaml.safe_load(f) or {}

# Move any plaintext provider key out of config.yaml before serving.
_migrated = secrets.migrate_from_config(_raw_config)
if _migrated:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(_raw_config, f, default_flow_style=False, allow_unicode=True)

api_key = _resolve_security_api_key(_raw_config)

WEB_CFG = _raw_config.get("web", {}) or {}
ENGINE_CFG = _raw_config.get("engine", {}) or {}
HOST = WEB_CFG.get("host", "127.0.0.1")
PORT = int(WEB_CFG.get("port", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.register("web", pid=os.getpid(), host=HOST, port=PORT)
    runtime.start_heartbeat(
        interval=float(ENGINE_CFG.get("watchdog_interval", 5)),
        restart_engine=bool(ENGINE_CFG.get("watchdog", True)),
    )
    try:
        yield
    finally:
        runtime.unregister("web")
        runtime.stop_heartbeat()
        if WEB_CFG.get("stop_engine_on_exit", False):
            runtime.stop_engine()


app = FastAPI(title="Drix", lifespan=lifespan)
if api_key:
    app.middleware("http")(AuthMiddleware(api_key=api_key, rate_limit=60))
app.include_router(router, prefix="/api")

icon_dir = ROOT / "ia_system" / "icon"
if icon_dir.is_dir():
    app.mount("/ia_system/icon", StaticFiles(directory=str(icon_dir)), name="icon")

cache_dir = ROOT / ".cache"
if cache_dir.is_dir():
    app.mount("/.cache", StaticFiles(directory=str(cache_dir)), name="cache")

FRONT_DIR = Path(__file__).resolve().parent / "front"
HTML_PATH = FRONT_DIR / "index.html"
CSS_PATH = FRONT_DIR / "style.css"
JS_PATH = FRONT_DIR / "script.js"

_NO_STORE = {"Cache-Control": "no-store"}


def _attach_session_cookie(response):
    """Give the browser an HttpOnly cookie so the key never touches JS."""
    if not api_key:
        return response
    response.set_cookie(
        COOKIE_NAME,
        api_key,
        max_age=86400,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


@app.get("/style.css", include_in_schema=False)
async def style_css():
    if CSS_PATH.exists():
        return FileResponse(CSS_PATH, media_type="text/css", headers=_NO_STORE)
    return HTMLResponse("", status_code=404)


@app.get("/script.js", include_in_schema=False)
async def script_js():
    if JS_PATH.exists():
        return FileResponse(JS_PATH, media_type="application/javascript", headers=_NO_STORE)
    return HTMLResponse("", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def root():
    if not HTML_PATH.exists():
        return HTMLResponse("<h1>Drix</h1><p>index.html não encontrado.</p>", status_code=404)
    html = HTML_PATH.read_text(encoding="utf-8")
    # The key is delivered through the HttpOnly cookie, never through the page.
    html = html.replace(
        "<script>window.__DRIX_KEY__ = '__DRIX_KEY__';</script>",
        "<script>window.__DRIX_KEY__ = '';</script>",
    )
    return _attach_session_cookie(HTMLResponse(html, headers=_NO_STORE))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning", log_config=None)

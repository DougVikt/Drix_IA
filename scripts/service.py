"""Drix service supervisor.

Modes::

    python scripts/service.py web        # web UI + indicator
    python scripts/service.py terminal   # embedded web server + terminal client
    python scripts/service.py headless   # web server only, no browser/indicator

Closing the browser does not stop the engine.  The desktop indicator
(``scripts/indicator.py``) stays visible and shows what is still running, so
the user always knows whether background services are active.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_MODELS", str(ROOT / "ia_system" / "models"))

from api import engine  # noqa: E402
from core import logs, runtime  # noqa: E402

with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f) or {}

WEB = _cfg.get("web") or {}
ENGINE = _cfg.get("engine") or {}
HOST = WEB.get("host", "127.0.0.1")
PORT = int(WEB.get("port", 8000))
STOP_ENGINE_ON_EXIT = bool(WEB.get("stop_engine_on_exit", False))
SHOW_INDICATOR = bool(WEB.get("indicator", True))


def _wait_port(host: str, port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.socket() as sock:
                if sock.connect_ex((host, port)) == 0:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _start_server():
    import uvicorn
    from ui.web_app import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True, name="drix-web")
    thread.start()
    return server


def _spawn_indicator() -> None:
    if not SHOW_INDICATOR:
        return
    pid = runtime.spawn_indicator()
    if pid:
        logs.info(f"Indicator started (pid {pid})")


def _shutdown(server=None) -> None:
    if server is not None:
        try:
            server.should_exit = True
        except Exception:
            pass
    runtime.unregister("web")
    runtime.stop_heartbeat()
    if STOP_ENGINE_ON_EXIT:
        engine.stop()
        logs.info("Engine stopped on exit (web.stop_engine_on_exit=true)")
    else:
        logs.info("Engine left running; use the Drix indicator to stop it")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "web"
    if mode not in ("web", "terminal", "headless"):
        print("usage: service.py [web|terminal|headless]", file=sys.stderr)
        return 2

    logs.setup()
    logs.info(f"Service starting in {mode} mode")

    if ENGINE.get("auto_start", True) and not engine.start():
        logs.warn("Engine could not be started")

    if engine.port_in_use():
        try:
            engine.sync_models()
        except Exception as exc:
            logs.warn(f"Model sync failed: {exc}")

    runtime.start_heartbeat(
        interval=float(ENGINE.get("watchdog_interval", 5)),
        restart_engine=bool(ENGINE.get("watchdog", True)),
    )

    server = None
    try:
        if mode == "terminal":
            server = _start_server()
            if not _wait_port(HOST, PORT):
                logs.error("Web server did not start in time")
                return 1
            _spawn_indicator()
            python = ROOT / ".venv" / "Scripts" / "python.exe"
            client = subprocess.Popen(
                [str(python), str(ROOT / "scripts" / "terminal_client.py")],
                cwd=str(ROOT),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            client.wait()
            return 0

        if mode == "headless":
            server = _start_server()
            while True:
                time.sleep(1)
            return 0

        # web mode
        _spawn_indicator()
        if WEB.get("auto_open", True):
            threading.Timer(1.2, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
        server = _start_server()
        while True:
            time.sleep(1)
        return 0

    except KeyboardInterrupt:
        return 0
    except Exception:
        try:
            (ROOT / "logs" / "service_error.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        return 1
    finally:
        _shutdown(server)


if __name__ == "__main__":
    raise SystemExit(main())

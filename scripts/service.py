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
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import yaml

sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_MODELS", str(ROOT / "ia_system" / "models"))

from core import python_runtime  # noqa: E402


def _ensure_pythonw() -> None:
    """Reinicia com pythonw.exe se estiver rodando com python.exe (evita console)."""
    if sys.platform != "win32":
        return
    if not sys.executable.lower().endswith("python.exe"):
        return
    pythonw = python_runtime.pythonw_exe()
    if not pythonw:
        return
    try:
        if Path(pythonw).resolve() == Path(sys.executable).resolve():
            return
    except Exception:
        pass

    log_path = ROOT / "logs" / "service_stderr.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = open(log_path, "a", encoding="utf-8", buffering=1)
        subprocess.Popen(
            [pythonw, str(__file__)] + sys.argv[1:],
            cwd=str(ROOT),
            env=python_runtime.child_env(),
            creationflags=0x08000000,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
        )
        log.close()  # the child keeps its own handle
    except Exception as exc:
        try:
            with open(ROOT / "logs" / "service_error.log", "a", encoding="utf-8") as fh:
                fh.write(f"Falha ao relancar com pythonw: {exc}\n")
        except Exception:
            pass
        return
    sys.exit(0)


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


def _wait_http(host: str, port: int, timeout: float = 90.0) -> bool:
    """Wait until the web app answers HTTP, not just until the port opens."""
    probe = "127.0.0.1" if host in ("", "0.0.0.0", "::") else host
    url = f"http://{probe}:{port}/"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=2.0) as resp:
                if int(getattr(resp, "status", 200)) < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _run_web_mode():
    """Start the server, wait until the UI responds, then open the browser."""
    server = _start_server()
    _spawn_indicator()
    if not WEB.get("auto_open", True):
        return server
    ready = _wait_http(HOST, PORT, timeout=90.0)
    if ready:
        logs.info(f"Web server ready; opening browser at http://{HOST}:{PORT}")
        try:
            webbrowser.open(f"http://{HOST}:{PORT}")
        except Exception as exc:
            logs.warn(f"Could not open the browser automatically: {exc}")
    else:
        logs.warn("Web server did not become ready; browser not opened")
    return server


def _warm_up() -> None:
    """Load the model and the memory/RAG caches before the first message.

    A cold 3B model takes 40-90 s to load from the external HD; doing it in
    the background while the page opens removes that wait from the first
    answer.  Mem0/Chroma initialisation is also moved off the request path.
    """
    if not ENGINE.get("preload", True):
        return
    model = engine.selected_model()
    if not model:
        return
    started = time.time()
    keep_alive = ENGINE.get("keep_alive", -1)
    try:
        from core import language as lang
        system = lang.get("system_prompt")
    except Exception:
        system = ""
    if not engine.model_fits_ram(model):
        logs.warn(f"Model preload skipped: {model} does not fit in RAM")
    elif engine.preload_model(model, keep_alive=keep_alive, system=system):
        # Prime the KV cache for the real system prompt so the first answer
        # does not have to process it from scratch.
        engine.preload_model(model, keep_alive=keep_alive, system=system)
        logs.info(f"Model preloaded: {model} ({time.time() - started:.1f}s)")
    else:
        logs.warn(f"Model preload failed: {model}")
    try:
        from core import main as core_main
        core_main.warm_caches()
        logs.info(f"Memory/context caches warmed ({time.time() - started:.1f}s)")
    except Exception as exc:
        logs.warn(f"Cache warmup failed: {exc}")


def _restore_front_page() -> None:
    """Restaura index.html a partir do backup criado pelo 'Parar tudo'."""
    front = ROOT / "ui" / "front"
    index = front / "index.html"
    backup = front / "index.html.bak"
    if backup.exists():
        try:
            if index.exists():
                index.unlink()
            backup.rename(index)
            logs.info("Página inicial restaurada após parada anterior")
        except Exception as exc:
            logs.warn(f"Falha ao restaurar index.html: {exc}")


def _shutdown(server=None) -> None:
    try:
        from core import memory_maintenance
        memory_maintenance.stop()
    except Exception:
        pass
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
    _ensure_pythonw()
    mode = sys.argv[1] if len(sys.argv) > 1 else "web"
    if mode not in ("web", "terminal", "headless"):
        print("usage: service.py [web|terminal|headless]", file=sys.stderr)
        return 2

    # systemd, docker stop and `kill` send SIGTERM; turn it into a clean
    # shutdown so the runtime state and the engine are handled properly.
    def _handle_term(signum, frame):
        raise KeyboardInterrupt

    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None and hasattr(signal, "signal"):
            try:
                signal.signal(signum, _handle_term)
            except Exception:
                pass

    logs.setup()
    logs.info(f"Service starting in {mode} mode")
    _restore_front_page()
    runtime.clear_stop()

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

    if ENGINE.get("preload", True):
        threading.Thread(target=_warm_up, daemon=True, name="drix-warmup").start()

    try:
        from core import memory_maintenance
        memory_maintenance.start()
        logs.info("Memory consolidation thread started")
    except Exception as exc:
        logs.warn(f"Memory consolidation could not start: {exc}")

    server = None
    try:
        if mode == "terminal":
            server = _start_server()
            if not _wait_port(HOST, PORT):
                logs.error("Web server did not start in time")
                return 1
            _spawn_indicator()
            python = python_runtime.python_exe()
            client = subprocess.Popen(
                [python, str(ROOT / "scripts" / "terminal_client.py")],
                cwd=str(ROOT),
                env=python_runtime.child_env(),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
            client.wait()
            return 0

        if mode == "headless":
            server = _start_server()
            while True:
                time.sleep(1)
            return 0

        # web mode: só abre o navegador depois que o servidor estiver
        # aceitando conexões.  Abrir antes mostra uma aba sem resposta
        # enquanto Mem0/modelo ainda estão inicializando.
        server = _run_web_mode()
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
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        try:
            (ROOT / "logs").mkdir(parents=True, exist_ok=True)
            (ROOT / "logs" / "service_error.log").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        except Exception:
            pass
        raise

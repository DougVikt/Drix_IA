"""Runtime supervision and global status for Drix.

Drix runs several processes: the bundled Ollama engine, the web server and
(optionally) the desktop indicator.  Closing the browser tab does *not* stop
anything -- this module keeps a heartbeat in ``data/runtime.json`` so any of
those processes (or the indicator) can see what is still alive and stop it
cleanly.

CLI::

    python -m core.runtime status
    python -m core.runtime start-engine
    python -m core.runtime stop
"""

from __future__ import annotations

import datetime
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "runtime.json"
INDICATOR_SCRIPT = ROOT / "scripts" / "indicator.py"
PYTHON_EXE = ROOT / ".venv" / "Scripts" / "python.exe"

_lock = threading.RLock()
_heartbeat_stop: threading.Event | None = None
_heartbeat_thread: threading.Thread | None = None


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _read() -> dict:
    if STATE_PATH.exists():
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("components", {})
                return data
        except Exception:
            pass
    return {"version": 1, "started_at": _now(), "components": {}}


def _write(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def register(name: str, **info) -> dict:
    with _lock:
        state = _read()
        current = state["components"].setdefault(name, {})
        current.update(info)
        current["registered_at"] = current.get("registered_at") or _now()
        current["updated_at"] = _now()
        state["updated_at"] = _now()
        _write(state)
        return current


def unregister(name: str) -> None:
    with _lock:
        state = _read()
        state["components"].pop(name, None)
        state["updated_at"] = _now()
        _write(state)


def heartbeat() -> None:
    with _lock:
        state = _read()
        state["updated_at"] = _now()
        state["pid"] = os.getpid()
        _write(state)


# ─── Liveness helpers ────────────────────────────────────────────

def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.socket() as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


def pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        return psutil.Process(int(pid)).is_running()
    except Exception:
        return False


def _kill_pid(pid, timeout: float = 5.0) -> bool:
    if not pid or int(pid) == os.getpid():
        return False
    try:
        proc = psutil.Process(int(pid))
    except Exception:
        return False
    try:
        for child in proc.children(recursive=True):
            try:
                child.kill()
            except Exception:
                pass
        proc.kill()
        proc.wait(timeout=timeout)
        return True
    except Exception:
        return False


# ─── Component actions ───────────────────────────────────────────

def engine_status() -> dict:
    from api import engine
    info = engine.status()
    info["host"] = "127.0.0.1"
    return info


def web_status() -> dict:
    state = _read()
    web = dict(state["components"].get("web") or {})
    host = web.get("host", "127.0.0.1")
    port = int(web.get("port") or 8000)
    web.update({
        "host": host,
        "port": port,
        "port_open": port_open(host, port),
        "pid_alive": pid_alive(web.get("pid")),
    })
    return web


def indicator_status() -> dict:
    state = _read()
    ind = dict(state["components"].get("indicator") or {})
    ind["pid_alive"] = pid_alive(ind.get("pid"))
    return ind


def start_engine() -> bool:
    from api import engine
    ok = engine.start()
    if ok:
        register("engine", pid=engine.status().get("engine_pid"),
                 port=engine.status().get("port"), running=True)
    return ok


def stop_engine() -> None:
    from api import engine
    engine.stop()
    unregister("engine")


def stop_web() -> bool:
    web = _read()["components"].get("web") or {}
    pid = web.get("pid")
    if pid and int(pid) == os.getpid():
        return False
    killed = _kill_pid(pid)
    unregister("web")
    return killed


def stop_indicator() -> bool:
    ind = _read()["components"].get("indicator") or {}
    pid = ind.get("pid")
    killed = _kill_pid(pid)
    unregister("indicator")
    return killed


def stop_all() -> dict:
    result = {"engine": False, "web": False, "indicator": False}
    try:
        stop_engine()
        result["engine"] = True
    except Exception:
        pass
    result["web"] = stop_web()
    result["indicator"] = stop_indicator()
    return result


def spawn_indicator() -> int | None:
    """Launch the desktop indicator as a detached process."""
    if not INDICATOR_SCRIPT.exists():
        return None
    python = PYTHON_EXE if PYTHON_EXE.exists() else Path(sys.executable)
    try:
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen(
            [str(python), str(INDICATOR_SCRIPT)],
            cwd=str(ROOT),
            creationflags=creation,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        register("indicator", pid=proc.pid)
        return proc.pid
    except Exception:
        return None


# ─── Status aggregation ──────────────────────────────────────────

def status() -> dict:
    state = _read()
    engine = engine_status()
    web = web_status()
    indicator = indicator_status()
    engine_running = bool(engine.get("port_open") or engine.get("engine_running"))
    return {
        "updated_at": state.get("updated_at"),
        "started_at": state.get("started_at"),
        "pid": state.get("pid"),
        "engine": {**engine, "running": engine_running},
        "web": web,
        "indicator": indicator,
        "any_running": bool(engine_running or web.get("port_open") or indicator.get("pid_alive")),
    }


# ─── Watchdog ────────────────────────────────────────────────────

def _watchdog_loop(stop_event: threading.Event, interval: float, restart_engine: bool) -> None:
    while not stop_event.wait(interval):
        try:
            heartbeat()
            if not restart_engine:
                continue
            engine = engine_status()
            if not engine.get("port_open"):
                from api import engine as engine_mod
                if engine_mod.start():
                    register("engine", pid=engine_status().get("engine_pid"),
                             port=engine_status().get("port"), running=True)
        except Exception:
            continue


def start_heartbeat(interval: float = 5.0, restart_engine: bool = True) -> None:
    global _heartbeat_stop, _heartbeat_thread
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        return
    _heartbeat_stop = threading.Event()
    _heartbeat_thread = threading.Thread(
        target=_watchdog_loop,
        args=(_heartbeat_stop, interval, restart_engine),
        daemon=True,
        name="drix-watchdog",
    )
    _heartbeat_thread.start()


def stop_heartbeat() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()


# ─── CLI ─────────────────────────────────────────────────────────

def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
        return 0
    if cmd == "start-engine":
        ok = start_engine()
        print(json.dumps({"started": ok, **engine_status()}, indent=2))
        return 0 if ok else 1
    if cmd == "stop-engine":
        stop_engine()
        print("engine stopped")
        return 0
    if cmd == "stop":
        print(json.dumps(stop_all(), indent=2))
        return 0
    if cmd == "indicator":
        pid = spawn_indicator()
        print(json.dumps({"indicator_pid": pid}))
        return 0 if pid else 1
    print("usage: python -m core.runtime [status|start-engine|stop-engine|stop|indicator]")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))

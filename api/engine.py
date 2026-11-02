"""Lifecycle management for the bundled Ollama engine."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psutil
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"
OLLAMA_BIN = ROOT / "ia_system" / "engine" / "ollama.exe"
MODELS_DIR = ROOT / "ia_system" / "models"
PIDFILE = ROOT / "data" / "engine.pid"

_DEFAULT_PORT = 11434
_DEFAULT_HOST = "127.0.0.1"

_proc: subprocess.Popen | None = None

if os.name == "nt":
    _SI = subprocess.STARTUPINFO()
    _SI.dwFlags = subprocess.STARTF_USESHOWWINDOW
    _SI.wShowWindow = 0
    _CW = subprocess.CREATE_NO_WINDOW
else:  # pragma: no cover - non Windows
    _SI = None
    _CW = 0


def _engine_cfg() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("engine") or {}
    except Exception:
        return {}


def engine_port() -> int:
    try:
        return int(_engine_cfg().get("port") or _DEFAULT_PORT)
    except (TypeError, ValueError):
        return _DEFAULT_PORT


def engine_host() -> str:
    return str(_engine_cfg().get("host") or _DEFAULT_HOST)


def _binary() -> str | None:
    if OLLAMA_BIN.exists():
        return str(OLLAMA_BIN)
    found = shutil.which("ollama")
    return found


def _get_env() -> dict:
    env = os.environ.copy()
    if MODELS_DIR.is_dir():
        env.setdefault("OLLAMA_MODELS", str(MODELS_DIR))
    env["OLLAMA_HOST"] = f"{engine_host()}:{engine_port()}"
    return env


def port_in_use(port: int | None = None, host: str | None = None) -> bool:
    port = port or engine_port()
    host = host or engine_host()
    try:
        with socket.socket() as sock:
            sock.settimeout(0.4)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False


def _listener_pids(port: int) -> list[int]:
    pids: list[int] = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if not conn.laddr or conn.laddr.port != port:
                continue
            if conn.status == psutil.CONN_LISTEN and conn.pid:
                pids.append(conn.pid)
    except Exception:
        pass
    return pids


def _owned_engine_pids() -> list[int]:
    """Ollama / llama-server processes that live inside this portable HD."""
    found = []
    root = str(ROOT).lower()
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in ("ollama.exe", "ollama", "llama-server.exe", "llama-server"):
                continue
            exe = (proc.info.get("exe") or "").lower()
            cmdline = " ".join(proc.cmdline()).lower()
            if exe.startswith(root) or root in cmdline:
                found.append(proc.info["pid"])
        except Exception:
            continue
    return found


def _read_pidfile() -> int | None:
    if not PIDFILE.exists():
        return None
    try:
        pid = int(PIDFILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None
    try:
        if psutil.Process(pid).is_running():
            return pid
    except Exception:
        pass
    return None


def start() -> bool:
    global _proc
    if port_in_use():
        return True
    binary = _binary()
    if not binary:
        return False
    try:
        _proc = subprocess.Popen(
            [binary, "serve"],
            env=_get_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_CW,
            startupinfo=_SI,
        )
    except Exception:
        _proc = None
        return False

    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(_proc.pid), encoding="utf-8")
    for _ in range(15):
        if port_in_use():
            return True
        if _proc.poll() is not None:
            break
        time.sleep(1)
    return port_in_use()


def _kill(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except Exception:
        return
    for child in parent.children(recursive=True):
        try:
            child.kill()
        except Exception:
            pass
    try:
        parent.kill()
        parent.wait(timeout=5)
    except Exception:
        pass


def stop() -> None:
    global _proc
    pids: set[int] = set()
    if _proc is not None and _proc.poll() is None:
        pids.add(_proc.pid)
    pid = _read_pidfile()
    if pid:
        pids.add(pid)
    pids.update(_listener_pids(engine_port()))
    pids.update(_owned_engine_pids())

    for pid in pids:
        if pid != os.getpid():
            _kill(pid)

    _proc = None
    try:
        PIDFILE.unlink(missing_ok=True)
    except Exception:
        pass


def is_running() -> bool:
    return bool(_read_pidfile() or port_in_use())


def _pid_for_status() -> int | None:
    pid = _read_pidfile()
    if pid:
        return pid
    pids = _listener_pids(engine_port())
    return pids[0] if pids else None


def fetch_models() -> list[str]:
    if not port_in_use():
        return []
    binary = _binary()
    if not binary:
        return []
    try:
        result = subprocess.run(
            [binary, "list"],
            capture_output=True, text=True, timeout=15,
            env=_get_env(), startupinfo=_SI, creationflags=_CW,
        )
    except Exception:
        return []
    names = []
    for line in result.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def sync_models() -> None:
    import core.hardware as hardware

    models = fetch_models()
    if not models:
        return

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    brain = cfg.setdefault("brain", {})
    brain["installed_models"] = models
    auto = brain.get("auto_select_model", True)
    if auto or brain.get("local_model") not in models:
        ram_gb = hardware._detect_ram_gb()
        selected, model_params = hardware.resolve_best(ram_gb, models)
        brain["local_model"] = selected
        brain["model_params"] = model_params

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

    cached = hardware.analyze(force=True)
    hardware._save_host_cache(cached)


def status() -> dict:
    pid = _pid_for_status()
    running = bool(pid or port_in_use())
    info = {
        "engine_running": running,
        "engine_pid": pid,
        "port": engine_port(),
        "host": engine_host(),
        "port_open": port_in_use(),
    }
    if pid:
        try:
            proc = psutil.Process(pid)
            info["uptime_s"] = int(time.time() - proc.create_time())
            info["memory_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass
    return info

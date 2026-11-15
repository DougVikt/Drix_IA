"""Lifecycle management for the bundled Ollama engine."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import threading
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

# Background model warmup queue.  Rapid model changes keep only the newest
# selection, and warmup yields while an answer is being generated.
_preload_lock = threading.Lock()
_preload_event = threading.Event()
_preload_pending: dict | None = None
_preload_started = False

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


def selected_model() -> str:
    """Model currently selected for the local engine."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return str((cfg.get("brain") or {}).get("local_model") or "").strip()
    except Exception:
        return ""


def _model_size_bytes(name: str) -> int:
    """On-disk size of a model, used as a rough RAM estimate."""
    try:
        import httpx
        resp = httpx.get(
            f"http://127.0.0.1:{engine_port()}/api/tags", timeout=5.0
        )
        resp.raise_for_status()
        for item in resp.json().get("models") or []:
            if str(item.get("name") or "") == name:
                return int(item.get("size") or 0)
    except Exception:
        pass
    return 0


def model_fits_ram(model: str | None = None) -> bool:
    """False when a model is clearly too large for this machine.

    A 7.6 GB model does not fit in 10 GB of RAM together with Windows and
    the other loaded models.  Warming it only blocks the engine for minutes
    and then fails; the chat itself can still try, but background warmup
    must not waste that time.
    """
    name = (model or selected_model()).strip()
    if not name:
        return False
    size = _model_size_bytes(name)
    if not size:
        return True
    try:
        total = float(psutil.virtual_memory().total)
    except Exception:
        return True
    # Leave room for Windows, the web app and any model already loaded.
    return size <= total * 0.72


def preload_model(model: str | None = None, keep_alive: str | int = -1,
                  timeout: float = 120.0, system: str = "",
                  messages: list[dict] | None = None) -> bool:
    """Load the chat model into RAM before the first user message.

    Loading a 2-4 GB model from the external HD takes 40-90 s on this
    hardware.  Doing it while the page is still opening removes that wait
    from the first answer.

    ``messages`` can carry the current conversation prefix (system + history)
    so the new model also warms its KV cache, not just the weights.
    """
    if not port_in_use():
        return False
    name = (model or selected_model()).strip()
    if not name:
        return False
    if not model_fits_ram(name):
        try:
            from core import logs
            total_gb = psutil.virtual_memory().total / (1024 ** 3)
            logs.warn(
                f"Model {name} is too large for {total_gb:.1f} GB RAM; "
                "preload skipped"
            )
        except Exception:
            pass
        return False
    try:
        import httpx
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        params = (cfg.get("brain") or {}).get("model_params") or {}
        options: dict = {"num_predict": 1}
        if params.get("ctx"):
            options["num_ctx"] = int(params["ctx"])
        if params.get("threads"):
            options["num_thread"] = int(params["threads"])
        url = f"http://127.0.0.1:{engine_port()}/api/chat"
        payload_messages = list(messages or [])
        if not payload_messages:
            if system:
                payload_messages.append({"role": "system", "content": system})
            payload_messages.append({"role": "user", "content": "ok"})
        payload = {
            "model": name,
            "messages": payload_messages,
            "stream": False,
            "keep_alive": keep_alive,
            "options": options,
        }
        resp = httpx.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return True
    except Exception:
        return False


def request_preload(model: str | None = None, keep_alive: str | int = -1,
                    message_builder=None) -> bool:
    """Queue a background warmup for the newest selected model.

    ``message_builder`` is evaluated right before the request, so a model
    changed during a long answer is warmed with the conversation as it is
    when the answer finishes.
    """
    global _preload_pending, _preload_started
    name = (model or selected_model()).strip()
    if not name:
        return False
    if not model_fits_ram(name):
        try:
            from core import logs
            logs.warn(f"Model warmup skipped: {name} does not fit in RAM")
        except Exception:
            pass
        return False
    job = {
        "model": name,
        "keep_alive": keep_alive,
        "builder": message_builder,
        "created": time.time(),
    }
    with _preload_lock:
        _preload_pending = job
        if not _preload_started:
            _preload_started = True
            threading.Thread(
                target=_preload_worker, daemon=True, name="drix-model-warmup"
            ).start()
    _preload_event.set()
    return True


def _chat_state() -> dict:
    try:
        from core import runtime as _runtime
        return _runtime.chat_state()
    except Exception:
        return {}


def _preload_worker() -> None:
    global _preload_pending
    while True:
        _preload_event.wait()
        _preload_event.clear()
        while True:
            with _preload_lock:
                job = _preload_pending
                _preload_pending = None
            if not job:
                break

            # Debounce: a second click within this window replaces the job
            # instead of loading two models.  Six seconds also gives the
            # user time to send the next message; an active answer always wins.
            deadline = time.time() + 6.0
            while time.time() < deadline:
                time.sleep(0.25)
                with _preload_lock:
                    if _preload_pending is not None:
                        break
            with _preload_lock:
                if _preload_pending is not None:
                    continue

            # Never compete with a response being generated.
            while True:
                state = _chat_state()
                if int(state.get("active", 0) or 0) == 0:
                    break
                with _preload_lock:
                    if _preload_pending is not None:
                        break
                time.sleep(0.5)
            with _preload_lock:
                if _preload_pending is not None:
                    continue

            # A chat that started after this model was selected already
            # loaded and used the model itself.  Warming on top of it would
            # only queue another request behind that answer.
            state = _chat_state()
            if float(state.get("last_started", 0) or 0) > float(
                job.get("created", 0) or 0
            ):
                continue

            if selected_model() != job["model"]:
                continue
            if not model_fits_ram(job["model"]):
                try:
                    from core import logs
                    logs.warn(
                        f"Model warmup skipped: {job['model']} does not fit in RAM"
                    )
                except Exception:
                    pass
                continue

            messages = None
            builder = job.get("builder")
            if builder is not None:
                try:
                    messages = builder()
                except Exception:
                    messages = None
            if selected_model() != job["model"]:
                continue

            # Last check right before the blocking request: if a message
            # arrived while the prefix was being built, let the chat win.
            if int(_chat_state().get("active", 0) or 0) > 0:
                continue

            started = time.time()
            ok = preload_model(
                job["model"],
                keep_alive=job["keep_alive"],
                messages=messages,
            )
            try:
                from core import logs
                scope = f", {len(messages)} mensagens" if messages else ""
                logs.info(
                    f"Model warmup {'ok' if ok else 'failed'}: "
                    f"{job['model']} ({time.time() - started:.1f}s{scope})"
                )
            except Exception:
                pass


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

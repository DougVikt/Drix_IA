import json
import os
import subprocess
import shutil
from pathlib import Path

from . import platform_paths

_SI_HIDDEN = None
try:
    _SI_HIDDEN = subprocess.STARTUPINFO()
    _SI_HIDDEN.dwFlags = subprocess.STARTF_USESHOWWINDOW
    _SI_HIDDEN.wShowWindow = 0
except Exception:
    pass
_CW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
_HIDDEN_KW = platform_paths.hidden_process_kwargs()

_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = _ROOT / "data" / "hardware_cache.json"
HOST_CACHE_PATH = None

if platform_paths.IS_WINDOWS:
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if appdata:
        HOST_CACHE_PATH = Path(appdata) / "drix_cache" / "hardware.json"
else:
    cache_base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    HOST_CACHE_PATH = Path(cache_base) / "drix" / "hardware.json"

_KNOWN_TIERS = {
    "llama3.1:8b":    (12, 8, 4096),
    "qwen2.5:7b":     (8,  6, 4096),
    "gemma3:12b":     (12, 8, 4096),
    "phi3.5:3.8b":    (6,  6, 4096),
    "phi3:3.8b":      (6,  6, 4096),
    "qwen2.5:3b":     (6,  6, 4096),
    "llama3.2:3b":    (4,  4, 2048),
    "tinyllama:1.1b": (0,  4, 2048),
    "nomic-embed-text": (2, 2, 512),
}

def _estimate_model_ram(model_name):
    import re
    m = re.search(r'[.:](\d+)b', model_name.lower())
    if m:
        size = int(m.group(1))
        if size >= 12: return 12
        if size >= 7: return 8
        if size >= 3: return 4
        return 2
    return 4

def _build_tiers(installed):
    tiers = []
    for model in installed:
        if model in _KNOWN_TIERS:
            ram, threads, ctx = _KNOWN_TIERS[model]
        else:
            ram = _estimate_model_ram(model)
            threads = min(ram, 8)
            ctx = 4096 if ram >= 8 else 2048
        tiers.append((ram, {"model": model, "threads": threads, "ctx": ctx}))
    tiers.sort(key=lambda x: -x[0])
    return tiers

def _detect_ram_gb():
    try:
        import psutil
        return round(psutil.virtual_memory().total / (1024 ** 3))
    except ImportError:
        pass
    if platform_paths.IS_WINDOWS:
        try:
            r = subprocess.run(
                ["wmic", "memorychip", "get", "capacity"],
                capture_output=True, text=True, timeout=5,
                startupinfo=_SI_HIDDEN, creationflags=_CW
            )
            total = sum(int(l.strip()) for l in r.stdout.strip().split("\n")[1:] if l.strip().isdigit())
            return round(total / (1024 ** 3))
        except Exception:
            return 8
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb / (1024 ** 2))
    except Exception:
        pass
    return 8

def _detect_cpu_cores():
    try:
        import psutil
        return psutil.cpu_count(logical=True)
    except ImportError:
        pass
    if platform_paths.IS_WINDOWS:
        try:
            r = subprocess.run(
                ["wmic", "cpu", "get", "NumberOfLogicalProcessors"],
                capture_output=True, text=True, timeout=5,
                startupinfo=_SI_HIDDEN, creationflags=_CW
            )
            lines = [l.strip() for l in r.stdout.strip().split("\n")[1:] if l.strip().isdigit()]
            return int(lines[0]) if lines else 4
        except Exception:
            return 4
    return os.cpu_count() or 4

def _pick_best_installed(ram_gb, tiers):
    supported = [info for ram, info in tiers if ram_gb >= ram]
    if len(supported) >= 2:
        return supported[1]
    return supported[0] if supported else None

def _pick_best_suggested(ram_gb):
    if ram_gb >= 12: return {"model": "llama3.1:8b", "threads": 8, "ctx": 4096}
    if ram_gb >= 8:  return {"model": "qwen2.5:7b", "threads": 6, "ctx": 4096}
    if ram_gb >= 6:  return {"model": "qwen2.5:3b", "threads": 6, "ctx": 4096}
    if ram_gb >= 4:  return {"model": "llama3.2:3b", "threads": 4, "ctx": 2048}
    return {"model": "tinyllama:1.1b", "threads": 4, "ctx": 2048}

def _detect_nvidia_gpu():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
            startupinfo=_SI_HIDDEN, creationflags=_CW
        )
        if r.returncode == 0 and r.stdout.strip():
            line = r.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            return {"name": parts[0], "vram": parts[1] if len(parts) > 1 else "?"}
    except Exception:
        pass
    return None

def _detect_amd_gpu():
    try:
        r = subprocess.run(
            ["rocm-smi", "--showproductname"],
            capture_output=True, text=True, timeout=5,
            startupinfo=_SI_HIDDEN, creationflags=_CW
        )
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if ":" in line and ("GPU" in line or "card" in line):
                    return {"name": line.split(":")[-1].strip()}
    except Exception:
        pass
    return None

def _detect_vulkan():
    try:
        r = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True, text=True, timeout=10,
            startupinfo=_SI_HIDDEN, creationflags=_CW
        )
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "deviceName" in line or "GPU id" in line:
                    return {"name": line.split("=")[-1].strip().strip('"')}
    except Exception:
        pass
    return None

def _load_host_cache(fingerprint):
    if not HOST_CACHE_PATH or not HOST_CACHE_PATH.exists():
        return None
    try:
        with open(HOST_CACHE_PATH) as f:
            cached = json.load(f)
        if cached.get("_fingerprint") == fingerprint:
            return cached
    except Exception:
        pass
    return None

def _save_host_cache(data):
    if not HOST_CACHE_PATH:
        return
    try:
        HOST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HOST_CACHE_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def _models_from_config():
    try:
        import yaml
        p = _ROOT / "config" / "config.yaml"
        with open(p) as f:
            cfg = yaml.safe_load(f)
        return cfg.get("brain", {}).get("installed_models", []) or []
    except Exception:
        return []

def resolve_best(ram_gb, installed_models):
    tiers = _build_tiers(installed_models) if installed_models else []
    best = _pick_best_installed(ram_gb, tiers)
    if not best:
        best = _pick_best_suggested(ram_gb)
    return best["model"], {"threads": best.get("threads", 4), "ctx": best.get("ctx", 2048)}

def analyze(force=False):
    ram_gb = _detect_ram_gb()
    cpu_cores = _detect_cpu_cores()
    fingerprint = f"{ram_gb}-{cpu_cores}"

    host_cache = _load_host_cache(fingerprint)
    if not force and host_cache:
        return host_cache

    if not force and CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            cached = json.load(f)
        if cached.get("_fingerprint") == fingerprint:
            _save_host_cache(cached)
            return cached

    installed = _models_from_config()
    selected, model_params = resolve_best(ram_gb, installed)

    nvidia = _detect_nvidia_gpu()
    amd = _detect_amd_gpu()
    vulkan = _detect_vulkan()

    result = {
        "_fingerprint": fingerprint,
        "ram_gb": ram_gb,
        "cpu_cores": cpu_cores,
        "installed_models": installed,
        "selected_model": selected,
        "model_params": model_params,
        "gpu_info": {
            "nvidia": nvidia,
            "amd": amd,
            "vulkan": vulkan,
        },
    }

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(result, f, indent=2)
    _save_host_cache(result)

    return result

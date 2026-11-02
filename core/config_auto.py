import os, sys, json, shutil, subprocess, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.yaml"

_venv = ROOT / ".venv" / "Lib" / "site-packages"
if _venv.exists():
    sys.path.insert(0, str(_venv))

import yaml

def sync_all():
    cfg = _load_config()
    changes = []
    changes.append(_sync_ollama_models_list(cfg))
    _save_config(cfg)
    changes.append(_sync_hardware_model(cfg))
    changes.append(_sync_skills(cfg))
    _save_config(cfg)
    return changes

def _load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def _save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)

def _sync_hardware_model(cfg):
    from . import hardware
    brain = cfg.setdefault("brain", {})
    if not brain.get("auto_select_model", True):
        return ""
    hw = hardware.analyze(force=True)
    old = brain.get("local_model")
    selected = hw.get("selected_model")
    if selected and selected != old:
        brain["local_model"] = selected
        brain["model_params"] = hw.get("model_params", {})
        return f"model: {old} → {selected}"
    return ""

def _sync_skills(cfg):
    skills_dir = ROOT / "skills"
    if not skills_dir.is_dir():
        return ""
    known = cfg.setdefault("skills", {}).setdefault("installed", [])
    found = sorted(f.stem for f in skills_dir.iterdir() if f.suffix == ".py" and f.stem != "__init__")
    new_skills = [s for s in found if s not in known]
    if new_skills:
        known.extend(new_skills)
        return f"skills: +{', '.join(new_skills)}"
    return ""

def _sync_ollama_models_list(cfg):
    _SI_HIDDEN = subprocess.STARTUPINFO()
    _SI_HIDDEN.dwFlags = subprocess.STARTF_USESHOWWINDOW
    _SI_HIDDEN.wShowWindow = 0
    _CW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

    ollama_bin = shutil.which("ollama")
    fallback = ROOT / "ia_system" / "engine" / "ollama.exe"
    if not ollama_bin and fallback.exists():
        ollama_bin = str(fallback)
    if not ollama_bin:
        return ""

    try:
        r = subprocess.run(
            [ollama_bin, "list"],
            capture_output=True, text=True, timeout=15,
            startupinfo=_SI_HIDDEN, creationflags=_CW,
            env={**os.environ, "OLLAMA_MODELS": str(ROOT / "ia_system" / "models")}
        )
        names = []
        for line in r.stdout.strip().split("\n")[1:]:
            parts = line.strip().split()
            if parts:
                names.append(parts[0])
        if not names:
            return ""
        brain = cfg.setdefault("brain", {})
        old = brain.get("installed_models", [])
        if names != old:
            brain["installed_models"] = names
            return f"models: {len(old)} → {len(names)}"
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    for change in sync_all():
        if change:
            print(change)

# Creation Guide — Drix

> How Drix is assembled, how to recreate the environment from scratch, and how to package it on a portable HD/SSD.
> Based on `DADOS_DEV/HISTORICO_DESENVOLVIMENTO.md` and `DADOS_DEV/STATUS_ATUAL.md`.

---

## Table of contents

- [Prerequisites](#prerequisites)
- [How Drix is packaged](#how-drix-is-packaged)
- [Setting up from scratch](#setting-up-from-scratch)
- [Folder structure](#folder-structure)
- [Embedded components](#embedded-components)
- [First start](#first-start)
- [Development and builds](#development-and-builds)
- [Common creation problems](#common-creation-problems)

---

## Prerequisites

- **Windows 10/11** (full experience) **or Linux** (supported: launcher, web/terminal/headless,
  embedded or system Ollama; desktop indicator when a graphical session is available).
  macOS uses the Linux code paths but is not tested yet.
- **External HD/SSD** with at least 30 GB free (heavy models require much more).
- **Python 3.10+** (3.10/3.11 recommended because `onnxruntime==1.16.3` has no wheels for
  newer versions on some platforms). The embedded Windows environment uses Python 3.10.11.
- **Git** (optional on the portable drive, required to contribute).
- Modern **browser** (Chrome, Firefox, Edge).
- **Offline** works by default in local mode.

Linux packages (Debian/Ubuntu):

```bash
sudo apt install python3 python3-venv python3-pip python3-tk ffmpeg git curl
```

Fedora:

```bash
sudo dnf install python3 python3-pip python3-tkinter ffmpeg git curl
```

## How Drix is packaged

Drix is a **self-contained launcher**: everything it needs lives in the root folder.

1. `start.bat` (Windows) or `start.sh` (Linux) sets `PATH` to the bundled Python, engine
   and `bin` folders, plus `OLLAMA_MODELS` pointing to `ia_system/models`.
2. `core/checker.py` calls `scripts/service.py`, which picks the mode (`web`, `terminal`, `headless`).
3. In `web` mode, the service starts on port `8000` and only opens the browser once the server responds.
4. The indicator (`scripts/indicator.py`) sits in the tray/status area with a **Stop all** option
   (on Linux it appears when `DISPLAY`/`WAYLAND_DISPLAY` is available).
5. `OLLAMA_MODELS` points to `ia_system/models` so Ollama finds local models.

## Setting up from scratch

The repository (git) contains **only code, configuration and icons**. The binary components are too large for git and are obtained separately:

| Component | Approx. size | How to get it (Windows) | How to get it (Linux) |
|-----------|--------------|--------------------------|------------------------|
| `.venv/` | 1.1 GB | `poetry install` (or `pip install` from `pyproject.toml`) | `./scripts/install_linux.sh` (Poetry or pip) |
| `ia_system/python/` | ~265 MB | **WinPython 3.10.11** portable, extracted into `ia_system\python\` | not needed — use `.venv/bin/python` |
| `ia_system/engine/` | ~1.85 GB | Portable **Ollama**: copy `ollama.exe` + DLLs into `ia_system\engine\` | copy the Linux `ollama` binary to `ia_system/engine/ollama`, or install Ollama system-wide |
| `ia_system/models/` | 21 GB+ | `ollama pull` with `OLLAMA_MODELS` pointing here | same |
| `ia_system/bin/` | ~1.1 GB | GNU tools (make.exe, libiconv/libintl) | optional: `pmtiles` for offline maps; `ffmpeg` from the system |
| `ia_system/poetry_cache/` | ~573 MB | optional; Poetry cache for offline installs | optional |

### Windows

```powershell
# 1. Clone or copy the repository to the external drive root (e.g. F:\)
git clone https://github.com/DougVikt/Drix_IA.git F:\

# 2. Place the portable components (WinPython + Ollama) under ia_system\
#    (copy from another Drix drive or download the official sources)

# 3. Create the virtual environment and install dependencies
python -m venv .venv
poetry install

# 4. Pull the default local model (start.bat already sets OLLAMA_MODELS)
F:\start.bat                       # starts the embedded Ollama engine
.venv\Scripts\python.exe -c "import subprocess; print(subprocess.run(['F:\ia_system\engine\ollama.exe','pull','phi3.5:3.8b']).returncode)"

# 5. Check and adjust the configuration
notepad config\config.yaml

# 6. (Optional) The knowledge base and downloads use folders under data/ and workspace/,
#    created automatically on first start.
```

### Linux

```bash
# 1. Clone or copy the repository (it can live on a normal disk)
git clone https://github.com/DougVikt/Drix_IA.git ~/Drix
cd ~/Drix

# 2. Create .venv and install dependencies (Poetry preferred, pip fallback)
#    If the scripts came from Windows/Git without the executable bit:
chmod +x start.sh scripts/install_linux.sh
./scripts/install_linux.sh

# 3. Ollama: use the system service or the portable binary
#    system:  curl -fsSL https://ollama.com/install.sh | sh
#    bundled: cp /path/to/ollama ia_system/engine/ollama && chmod +x ia_system/engine/ollama

# 4. Pull the default model
export OLLAMA_MODELS="$PWD/ia_system/models"
ollama pull phi3.5:3.8b            # or: ia_system/engine/ollama pull phi3.5:3.8b

# 5. Check and adjust the configuration
$EDITOR config/config.yaml

# 6. Start Drix (web/terminal/headless)
#    If start.sh is not executable: chmod +x start.sh
./start.sh
```

> **Essential to run:** `start.bat` / `start.sh`, `pyproject.toml` + `poetry.lock`,
> `config/config.yaml`, `ia_system/icon/*.png` (versioned) and the binary components in the
> table above. Everything under `data/` is created automatically on first start — see
> [`data/README.md`](../data/README.md).

```powershell
# Windows: quick check that everything came up
Test-NetConnection 127.0.0.1 -Port 8000   # API/web
Test-NetConnection 127.0.0.1 -Port 11434  # Ollama
Get-Content F:\logs\drix.log -Tail 20     # service log
```

```bash
# Linux: quick check that everything came up
ss -ltnp | grep -E ':(8000|11434)\b'
tail -n 20 logs/drix.log
```

## Folder structure

```
Drix/
├── api/            # FastAPI REST: /model, /providers, /chat, /downloads, /knowledge...
├── config/         # config.yaml — main configuration
├── core/           # Core: agent, providers, memory, tools, downloader, knowledge, runtime...
├── data/           # Persistent data: conversations, memories, secrets.json, knowledge_db...
├── docs/           # User guides (this file and CONFIGURATION.md)
├── ia_system/      # Ollama (engine), models, icons; embedded Python on Windows
├── logs/           # drix.log / all.log
├── scripts/        # start.py, service.py, indicator.py, install_linux.sh, update_dump.py
├── skills/         # Skills (audio, automation, image, video, vision)
├── tests/          # unittest suite
├── ui/             # Web front (HTML/CSS/JS) + web_app.py (FastAPI)
├── workspace/      # Work area; downloads default to workspace/downloads
├── .venv/          # Virtual environment
├── Makefile        # Cross-platform (Windows and Linux)
├── pyproject.toml  # Poetry
├── start.bat       # Windows launcher
└── start.sh        # Linux/macOS launcher
```

## Embedded components

| Item | Role | Versioned? |
|------|------|------------|
| `ia_system/engine/ollama.exe` / `ollama` | Portable Ollama engine (Windows / Linux) | No — obtain separately |
| `ia_system/models/` | Local Ollama models | No — `ollama pull` |
| `ia_system/python/` | Embedded Python 3.10.11 (WinPython, Windows only) | No — obtain separately |
| `ia_system/bin/` | GNU tools (make, iconv) and optional `pmtiles` | No — obtain separately |
| `ia_system/icon/` | UI logos (`logo_drix2.png`, `logo_nome_drix.png`) | **Yes** (`.gitignore` exception) |
| `.venv/` | Virtual environment with dependencies | No — `poetry install` / `install_linux.sh` |
| `config/config.yaml` | Main configuration (YAML) | **Yes** |
| `data/` | Runtime data (conversations, memories, secrets) | No — created at runtime |

> `DADOS_DEV/` holds development documentation; it is not sensitive, just not versioned by project decision.

## First start

Windows:

```powershell
F:\start.bat
```

Linux:

```bash
./start.sh
```

Expected output (summary):

1. `core/checker.py` verifies the environment.
2. `scripts/service.py` asks/starts the mode.
3. In `web` mode, opens `http://127.0.0.1:8000`.
4. The indicator appears in the tray/status bar (on Linux, when a display is available).

## Development and builds

```powershell
# Run tests
python -m unittest discover -s tests -v

# Compile all modules to check syntax
python -m py_compile $(Get-ChildItem -Recurse -Filter *.py | Select-Object -ExpandProperty FullName)

# Refresh dependencies in the venv
poetry lock && poetry install

# Makefile (Windows or Linux)
make test
make self-test
```

```bash
# Linux equivalents
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile $(find . -name '*.py' -not -path './.venv/*')
poetry lock && poetry install
make test
```

Checklist before committing:

1. `python -m py_compile` on every changed module.
2. `python -m unittest` (when available).
3. Check `git status` — nothing from `data/`, `logs/`, `workspace/` or `DADOS_DEV/` committed.
4. If touching secrets, never commit `config/config.yaml` with plaintext keys.
5. Update this guide if the structure or prerequisites change.

## Common creation problems

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `start.bat` opens and closes | Embedded Python missing or corrupt | Check `ia_system/python/` |
| `start.sh` says Python 3.10+ missing | No venv/system Python | Run `scripts/install_linux.sh` |
| Ollama does not start | Port 11434 busy | Close external Ollama or change the port |
| UI does not load | Import error in `web_app.py` | Check `logs/drix.log` |
| Model does not preload | Model not downloaded | `start.bat`/`start.sh` → web mode → switch model |
| Download fails | yt-dlp outdated | Update `pyproject.toml` + refresh venv |
| Indicator does not appear on Linux | No graphical session or tkinter missing | Use web/headless mode or install `python3-tk` |
| `onnxruntime` install fails on Linux | Python 3.12/3.13 without a wheel for 1.16.3 | Use Python 3.10/3.11 |

---

*Document created from the Drix operational state and functional reference on 2026-11-14.*

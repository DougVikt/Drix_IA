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

## Prerequisites

- **Windows 10/11** (full experience). Linux/macOS: core and API run, but the launcher,
  tray indicator and DPAPI vault are Windows-only — see [Compatibility](README.md#compatibility) in the README.
- **External HD/SSD** with at least 30 GB free (heavy models require much more).
- **Python 3.10+** (the embedded environment uses Python 3.10.11).
- **Git** (optional on the portable drive, required to contribute).
- Modern **browser** (Chrome, Firefox, Edge).
- **Offline** works by default in local mode.

## How Drix is packaged

Drix is a **self-contained launcher**: everything it needs lives in the root folder.

1. `start.bat` sets `PATH` to `ia_system\python`, `ia_system\bin` and `ia_system\engine`, plus `OLLAMA_MODELS` pointing to `ia_system\models`.
2. `core/checker.py` calls `scripts/service.py`, which picks the mode (`web`, `terminal`, `headless`).
3. In `web` mode, the service starts on port `8000` and only opens the browser once the server responds.
4. The indicator (`scripts/indicator.py`) sits in the tray/status area with a **Stop all** option.
5. `OLLAMA_MODELS` points to `ia_system\models` so Ollama finds local models.

## Setting up from scratch

The repository (git) contains **only code, configuration and icons**. The binary components are too large for git and are obtained separately:

| Component | Approx. size | How to get it |
|-----------|--------------|---------------|
| `.venv/` | 1.1 GB | `poetry install` (or `pip install` from `pyproject.toml`) |
| `ia_system/python/` | ~265 MB | **WinPython 3.10.11** portable, extracted into `ia_system\python\` |
| `ia_system/engine/` | ~1.85 GB | Portable **Ollama**: copy `ollama.exe` + DLLs into `ia_system\engine\` |
| `ia_system/models/` | 21 GB+ | `ollama pull` with `OLLAMA_MODELS` pointing here |
| `ia_system/bin/` | ~1.1 GB | GNU tools (make.exe, libiconv/libintl) |
| `ia_system/poetry_cache/` | ~573 MB | optional; Poetry cache for offline installs |

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

> **Essential to run:** `start.bat`, `pyproject.toml` + `poetry.lock`, `config/config.yaml`,
> `ia_system/icon/*.png` (versioned) and the binary components in the table above.
> Everything under `data/` is created automatically on first start — see [`data/README.md`](../data/README.md).

```powershell
# Quick check that everything came up
Test-NetConnection 127.0.0.1 -Port 8000   # API/web
Test-NetConnection 127.0.0.1 -Port 11434  # Ollama
Get-Content F:\logs\drix.log -Tail 20     # service log
```

## Folder structure

```
F:\
├── api/            # FastAPI REST: /model, /providers, /chat, /downloads, /knowledge...
├── config/         # config.yaml — main configuration
├── core/           # Core: agent, providers, memory, tools, downloader, knowledge, runtime...
├── data/           # Persistent data: conversations, memories, secrets.json, knowledge_db...
├── docs/           # User guides (this file and CONFIGURATION.md)
├── ia_system/      # Portable Ollama (engine), models, embedded Python, icons
├── logs/           # drx.log / all.log
├── scripts/        # start.py, service.py, indicator.py, update_dump.py
├── skills/         # Skills (audio, automation, image, video, vision)
├── tests/          # unittest suite
├── ui/             # Web front (HTML/CSS/JS) + web_app.py (FastAPI)
├── workspace/      # Work area; downloads default to workspace/downloads
├── .venv/          # Virtual environment
├── Makefile
├── pyproject.toml  # Poetry
└── start.bat       # Launcher
```

## Embedded components

| Item | Role | Versioned? |
|------|------|------------|
| `ia_system/engine/ollama.exe` | Portable Ollama engine | No — obtain separately |
| `ia_system/models/` | Local Ollama models | No — `ollama pull` |
| `ia_system/python/` | Embedded Python 3.10.11 (WinPython) | No — obtain separately |
| `ia_system/bin/` | GNU tools (make, iconv) | No — obtain separately |
| `ia_system/icon/` | UI logos (`logo_drix2.png`, `logo_nome_drix.png`) | **Yes** (`.gitignore` exception) |
| `.venv/` | Virtual environment with dependencies | No — `poetry install` |
| `config/config.yaml` | Main configuration (YAML) | **Yes** |
| `data/` | Runtime data (conversations, memories, secrets) | No — created at runtime |

> `DADOS_DEV/` holds development documentation; it is not sensitive, just not versioned by project decision.

## First start

```powershell
F:\start.bat
```

Expected output (summary):

1. `core/checker.py` verifies the environment.
2. `scripts/service.py` asks/starts the mode.
3. In `web` mode, opens `http://127.0.0.1:8000`.
4. The indicator appears in the tray/status bar.

## Development and builds

```powershell
# Run tests
python -m unittest discover -s tests -v

# Compile all modules to check syntax
python -m py_compile $(Get-ChildItem -Recurse -Filter *.py | Select-Object -ExpandProperty FullName)

# Refresh dependencies in the venv
poetry lock && poetry install

# Makefile (Linux/WSL or with make available)
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
| Ollama does not start | Port 11434 busy | Close external Ollama or change the port |
| UI does not load | Import error in `web_app.py` | Check `logs/drix.log` |
| Model does not preload | Model not downloaded | `F:\start.bat` → web mode → switch model |
| Download fails | yt-dlp outdated | Update `pyproject.toml` + refresh venv |

---

*Document created from the Drix operational state and functional reference on 2026-11-14.*

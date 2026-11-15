# Drix — Portable AI

<div  align="center">
<img src="ia_system/icon/logo_drix2.png" height="90" alt="Drix icon">
<img src="ia_system/icon/logo_nome_drix.png" height="80" alt="Drix">
</div>
<br>

> **Version:** `0.1.0-alpha` · **License:** MIT · **Status:** functional, in active development

Portable AI assistant: runs straight from an external HD/SSD, installing nothing on the host PC.
Embedded Ollama engine, lightweight web UI, terminal and headless modes, persistent memory,
agents, URL media downloads, and a local knowledge base (RAG).

---

## Table of contents

- [What it is](#what-it-is)
- [Features](#features)
- [Quick start](#quick-start)
- [Documentation](#documentation)
- [Project structure](#project-structure)
- [Security](#security)
- [License](#license)

---

## What it is

Drix is built to be **independent of the host PC**: everything it needs lives in the
root folder of the portable drive — embedded Python, Ollama, models, data and configuration.

- **Local by default:** models run on the embedded engine (`ia_system/`), no internet required.
- **Optional online providers:** OpenAI, Anthropic and any OpenAI-compatible endpoint.
- **Privacy:** API keys live in a local vault (DPAPI on Windows) and/or environment
  variables — never in plaintext in `config.yaml`.

## Features

| Area | What it does |
|------|-----------|
| Chat | SSE streaming, per-workspace history, attachments, light/dark theme |
| Models | Hardware-based selection, optimized switch, background preload |
| Agents | Tool calling with permissions, subagents (`coder`, `researcher`, `summarizer`) |
| Memory | SQLite + Chroma, background consolidation, context compaction |
| Web | Search/fetch with network policy and SSRF blocking, content treated as untrusted |
| Downloads | yt-dlp + portable ffmpeg: video/audio by URL, queue, progress and cancel |
| Knowledge | Local RAG in SQLite: upload PDF/DOCX/TXT/…, semantic search, sources cited in chat |
| Tools | Shell, files, memory, snapshots, MCP, skills (audio, image, video, vision) |

## Quick start

```powershell
# 1. Plug in the external HD/SSD as F:
# 2. Run the launcher
F:\start.bat
```

> New machine? First set up the portable components (WinPython, Ollama, models) following
> [`docs/CREATION.md`](./docs/CREATION.md#setting-up-from-scratch).

To stop, use **Stop all** in the services panel (indicator). Never close the indicator window
with the X — closing is disabled on purpose to force a safe stop.

Quick check:

```powershell
Test-NetConnection 127.0.0.1 -Port 8000   # API/web
Test-NetConnection 127.0.0.1 -Port 11434  # Ollama
```

## Documentation

Detailed guides live in [`docs/`](./docs), kept separate so the README stays short:

| Document | Use when you want to... |
|-----------|----------------------|
| [`docs/CREATION.md`](./docs/CREATION.md) | Understand how Drix is assembled, recreate the environment from scratch, folder structure and builds |
| [`docs/CONFIGURATION.md`](./docs/CONFIGURATION.md) | Configure everything: `config.yaml`, environment variables, API keys, permissions, network |
| [`DADOS_DEV/`](./DADOS_DEV/) | Development documentation (history, full reference, status) — **local, not versioned** |

## Project structure

```
F:\
├── api/            # FastAPI: auth, engine, REST routes
├── client/         # Drix client (terminal/API)
├── config/         # config.yaml (main configuration)
├── core/           # Core: agent, providers, tools, memory, downloader, knowledge...
├── data/           # Persistent data (conversations, memories, secrets, knowledge)
├── docs/           # User guides (creation and configuration)
├── ia_system/      # Portable Ollama + models + embedded Python
├── logs/           # drx.log / all.log
├── scripts/        # start.py, service.py, indicator.py, update_dump.py
├── skills/         # Installed skills
├── tests/          # Tests (unittest)
├── ui/             # Web interface (front) + web_app.py
├── workspace/      # Work area; downloads/ by default
├── .venv/          # Virtual environment
├── Makefile
├── pyproject.toml  # Poetry · version 0.1.0-alpha
└── start.bat       # Launcher
```

## Security

- API key auth + `HttpOnly`/`SameSite=Strict` cookie; CSRF by same origin.
- Rate limit (60 req/min general, 30 req/min chat); polling exempt.
- SSRF: private/loopback IP blocking and allowed-domains list.
- Secrets in `data/secrets.json` (DPAPI, hidden on Windows) or env vars
  (`DRIX_SECURITY_API_KEY`, `DRIX_<PROVIDER>_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
- Web content and knowledge snippets are treated as **untrusted** in prompts.
- Details in [`docs/CONFIGURATION.md`](./docs/CONFIGURATION.md#security-and-keys).

## License

MIT — see [`LICENSE`](./LICENSE).

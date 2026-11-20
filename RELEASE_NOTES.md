# Release Notes — v0.1.0-alpha

> Portable AI: runs straight from an external HD/SSD, installing nothing on the host PC.
> Embedded Ollama engine, lightweight web UI, terminal/headless modes, persistent memory,
> agents, URL media downloads and a local knowledge base (RAG).

## Highlights
- **Local knowledge base (RAG)** — upload PDF/DOCX/TXT/CSV/JSON, SQLite indexing,
  semantic + keyword search, sources cited in chat (`core/knowledge.py`)
- **Media downloads by URL** — yt-dlp + portable ffmpeg: queue, progress, cancel (`core/downloader.py`)
- **Optimized model switch** — single write to config + background preload
- **Informative startup** — active vs. suggested model, last used model, network permissions
- **Updated web UI** — new layout, complete settings panel and stop page
- **Linux support** — `start.sh` + `scripts/install_linux.sh`, cross-platform paths,
  bundled or system Ollama and clean SIGTERM shutdown (`core/platform_paths.py`)

## Security
- API keys: **env var > local vault (DPAPI on Windows, `0600` file on Linux) > legacy config** — never plaintext in `config.yaml`
- Vault `data/secrets.json` hidden; keys registered via web go to the vault
- API key auth + `HttpOnly`/`SameSite=Strict` cookie, same-origin CSRF, rate limit and SSRF blocking

## Fixes
- Model switch no longer stalls the web service (redundant config writes)
- Page no longer closes itself after switching models (false positive in runtime polling)
- Crash `core.secrets.token_hex` at startup
- CSRF/session cookie; X-close on the indicator disabled ("Stop all" is the safe path)

## Docs
- Restructured README + guides in `docs/` (`CREATION.md`, `CONFIGURATION.md`, index)
- Icons versioned in the repo; `data/README.md` documents the runtime folder

## Installation notes
- The repo only ships code + config + icons; binaries (WinPython, Ollama, models, `.venv`)
  are obtained separately — see [`docs/CREATION.md`](docs/CREATION.md)
- `data/`, `logs/`, `workspace/`, `DADOS_DEV/` and `ia_system/` binaries are not versioned

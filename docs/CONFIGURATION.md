# Configuration Guide — Drix

> How to configure Drix end to end: `config.yaml`, environment variables, API keys, permissions, network and the knowledge base.
> Based on `DADOS_DEV/DRIX_COMPLETO.md`, `DADOS_DEV/medidas de segurança.md` and the current operational state.

---

## Table of contents

- [Overview and files](#overview-and-files)
- [How configuration is loaded](#how-configuration-is-loaded)
- [`config.yaml` sections](#configyaml-sections)
- [Environment variables](#environment-variables)
- [Security and keys](#security-and-keys)
- [Network and SSRF blocking](#network-and-ssrf-blocking)
- [Tool permissions](#tool-permissions)
- [Configuration via the web UI](#configuration-via-the-web-ui)
- [Common examples](#common-examples)
- [Verification and troubleshooting](#verification-and-troubleshooting)

---

## Overview and files

| File/folder | Purpose |
|-------------|---------|
| `config/config.yaml` | Main configuration (read at boot, partially reloaded) |
| `data/secrets.json` | Secrets vault (DPAPI on Windows, `0600` local file on Linux/macOS) |
| `data/runtime.json` | Runtime state (indicator, pids, ports) |
| `data/conversations.db` | Conversation history (terminal) |
| `data/web_conversations.db` | Conversation history (web) |
| `data/knowledge/` | Documents uploaded to the knowledge base |
| `data/knowledge_db/` | Knowledge base SQLite index |
| `data/maps/` | Offline map catalog and `.pmtiles` files (see [`MAPS.md`](./MAPS.md)) |
| `data/vector_db/` | Legacy RAG memory (Chroma) — do not delete |
| `data/lessons/` | Memory/learning — do not delete |
| `logs/drix.log` | Service log |

## How configuration is loaded

1. At boot, `core/main.py` reads `config/config.yaml` and applies:
   - **env var overrides** for sensitive keys (`security.api_key` ← `DRIX_SECURITY_API_KEY`).
   - **reference resolution** for `{env:VAR}`, `${VAR}` and `$VAR` in text values.
   - **automatic model selection** by hardware, if `brain.auto_select_model` or `local_model` is missing.
2. Changes via API (`/api/settings`, `/api/providers/config`) pass sanitization before saving:
   - `security.api_key` and `operation.api_key` are **never** persisted in plaintext.
   - Only `{env:...}` / `${...}` references or empty values.
3. `ConfigManager.reload()` re-reads the file; most changes take effect immediately, some require a service restart.

## `config.yaml` sections

### `operation` — Mode and provider

```yaml
operation:
  mode: local              # local | api
  provider: local          # local | ollama | openai | anthropic | compatible
  api_provider: openai     # provider when mode=api
  model: phi3.5:3.8b
  base_url: ''             # empty = provider default URL
  fallback_local: true     # fall back to local if the provider fails
  temperature: 0.7
  max_tokens: 1024
  timeout: 120.0
  keep_alive: -1
  api_key: ''              # ALWAYS empty here; use env var or vault
```

### `brain` — Models and hardware

```yaml
brain:
  local_model: phi3.5:3.8b
  auto_select_model: false   # true = pick by hardware on every start
  auto_scan: true
  installed_models: [...]
  lessons_folder: ./data/lessons
  memory_db: ./data/vector_db
  chunk_size: 1000
  model_params:
    ctx: 4096
    threads: 6
```

### `engine` — Ollama engine

```yaml
engine:
  auto_start: true
  host: 127.0.0.1
  port: 11434
  preload: true             # preload the model on start
  watchdog: true
  watchdog_interval: 5
  keep_alive: -1
```

### `web` — Server/UI

```yaml
web:
  host: 127.0.0.1           # do NOT use 0.0.0.0 without HTTPS + stronger auth
  port: 8000
  auto_open: true
  indicator: true
  stop_engine_on_exit: false
```

### `network` — Internet and SSRF

```yaml
network:
  allow_internet_access: true
  block_local_network: true
  allowed_domains: []        # empty = all (respecting blocks)
  request_timeout: 15
```

### `knowledge` — Knowledge base (RAG)

```yaml
knowledge:
  enabled: true
  dir: ./data/knowledge
  db: ./data/knowledge_db
  max_file_mb: 50
  chunk_size: 1000
  chunk_overlap: 200          # must be < chunk_size
  top_k: 4
  context_chars: 1800
```

- Accepted formats: **PDF, DOCX, TXT, MD/Markdown, HTML/HTM, CSV and JSON**.
- Legacy `.doc` is **not** supported; convert it to `.docx` first.
- PDF extraction uses `pypdf`; DOCX uses `docx2txt`. If a reader is missing, the document stays listed with an actionable error.
- Originals stay in `knowledge.dir/files`; the SQLite index is in `knowledge.db`. The index stores paths **relative to `knowledge.dir`** (for example `files/<stored_name>`), so the base keeps working after moving the project to another disk, another PC or Linux. Legacy absolute paths are migrated automatically when the list is read.
- Uploads are indexed in a background thread (`queued` → `indexing` → `ready`/`error`). Search uses Ollama embeddings and falls back to keyword ranking when the engine is offline.

### `downloads` — Media downloads

```yaml
downloads:
  enabled: true
  dir: ./workspace/downloads
  max_concurrent: 2           # 1 to 4
  ffmpeg: ''                  # empty = imageio-ffmpeg or PATH
  proxy: ''
  cookies: ''                 # path to cookies.txt
```

### `maps` — Offline maps

```yaml
maps:
  enabled: true
  dir: ./data/maps
  source_url: https://build.protomaps.com/20261118.pmtiles
  max_parallel_downloads: 1   # reserved; this version runs one job at a time
  allow_private_hosts: false  # true only for local mirrors (http/private IPs)
```

- `dir` must resolve inside the Drix root; outside paths are ignored and
  `data/maps` is used. `~`, `$VAR`, `${VAR}` and `%VAR%` are expanded on both
  Windows and Linux.
- `source_url` is the full-planet PMTiles build used by presets and extraction.
- Regional extraction needs the `pmtiles` CLI in `ia_system/bin/` (or `PATH`):
  `pmtiles.exe` on Windows, `pmtiles` on Linux/macOS. URL downloads and local
  imports do not need it.
- `allow_private_hosts` also allows plain `http://` URLs. Keep it `false`
  unless you use a local mirror; the host is checked again after redirects.
- Presets and aliases live in `config/maps_presets.yaml`. Full guide:
  [`MAPS.md`](./MAPS.md).

### `memory` — Memory and consolidation

```yaml
memory:
  infer: false
  inject_min_score: 0.6
  search_timeout: 3.5
  context_timeout: 4.0
  block_ttl_minutes: 60
  consolidate:
    enabled: true
    use_llm: true
    idle_minutes: 5
    interval_minutes: 10
    batch_size: 8
    min_entries: 8
    keep_recent: 6
    max_batches_per_run: 2
    max_tokens: 256
    retry_hours: 24
```

### `compaction`, `snapshots`, `history`, `agents`, `mcp`, `skills`, `tools`

- `compaction.enabled`, `keep_recent`, `max_tokens`, `use_llm` — context compaction.
- `snapshots.enabled`, `max: 20` — file snapshots.
- `history.enabled`, `max_conversations: 50` — conversation history.
- `agents.enabled`, subagents `coder`, `researcher`, `summarizer`.
- `mcp.enabled`, `servers` — disabled by default.
- `skills.*` — audio, automation, image, video, vision skills.
- `tools.enabled`, `max_steps`, `permissions` — see the permissions section.

## Environment variables

| Variable | Use | Priority |
|----------|-----|----------|
| `DRIX_SECURITY_API_KEY` | API/UI auth key | Highest for `security.api_key` |
| `DRIX_<PROVIDER>_API_KEY` | Provider key (e.g. `DRIX_OPENAI_API_KEY`) | Above the vault |
| `OPENAI_API_KEY` | Fallback for OpenAI | Vault > empty |
| `ANTHROPIC_API_KEY` | Fallback for Anthropic | Above the vault |
| `OLLAMA_MODELS` | Ollama models path | Set by the launcher |

In `config.yaml` you can reference env vars:

```yaml
security:
  api_key: '{env:DRIX_SECURITY_API_KEY}'
```

## Security and keys

1. **Never** put a real `security.api_key` or `operation.api_key` value in `config.yaml` — Drix sanitizes on save, but avoid it.
2. Prefer **environment variables** for keys that change per environment:
   ```powershell
   $env:DRIX_SECURITY_API_KEY = "generate-with-openssl-or-python"
   $env:DRIX_OPENAI_API_KEY = "sk-..."
   ```
   ```bash
   export DRIX_SECURITY_API_KEY="generate-with-openssl-or-python"
   export DRIX_OPENAI_API_KEY="sk-..."
   ```
3. Or use the **local vault** (`data/secrets.json`; DPAPI on Windows, `0600` local file
   with base64 obfuscation on Linux/macOS): keys registered on the web
   (`POST /api/providers/config`) go to the vault, never to the YAML.
4. To remove a saved key: `DELETE /api/providers/{provider}/key` (or Settings panel → providers).
5. Effective priority: **env var > vault > legacy config**.
6. Extra security:
   - Cookie `HttpOnly` + `SameSite=Strict`.
   - CSRF: `Sec-Fetch-Site` same-origin or matching `Origin`/`Referer`.
   - `web.host: 127.0.0.1` by default — for LAN, use HTTPS + stronger auth + firewall.
   - On Linux the vault file is created with mode `0600`; it is not encrypted with a
     machine key, so keep `data/` out of backups/sync services you do not trust.

## Network and SSRF blocking

- `network.allow_internet_access: false` blocks web search/fetch for everyone.
- `network.block_local_network: true` prevents access to private/loopback IPs.
- `network.allowed_domains` — allowlist if you want to restrict.
- Every URL passes IP and redirect checks.

## Tool permissions

Each tool has `allow`, `ask` or `deny` in `tools.permissions`:

| Tool | Current default | Notes |
|------|-----------------|-------|
| `read_file` | `allow` | Read |
| `write_file` | `ask` | Write requires confirmation |
| `run_shell` | `deny` | Disabled for safety |
| `fetch_url` | `allow` | Subject to SSRF |
| `web_search` | `allow` | Subject to SSRF |
| `download_media` | `ask` | Download requires confirmation |
| `download_info/status/list/cancel` | `allow` | Metadata/control |
| `knowledge_search` | `allow` | Local base search |
| `knowledge_list` | `allow` | List documents |
| `maps_list/info/status/search/open` | `allow` | Local map catalog and viewer |
| `maps_download`, `maps_extract` | `ask` | Network and disk; confirmation before starting |
| `maps_delete` | `ask` | Deletes the local `.pmtiles` file |
| `snapshot_restore` | `allow` | Restore |

Change via the **Tools** tab in settings or in `config.yaml`.

`tools.default_permission` is `ask`: tools without an explicit rule prompt
before running. When the user chooses **remember**, the decision is stored
outside the project, keyed by a hash of the tool arguments:

- Windows: `%LOCALAPPDATA%\Drix\permissions.json`
- Linux/macOS: `~/.cache/drix/permissions.json` (or `$XDG_CACHE_HOME/drix`)

The cache contains the tool name, the argument hash and a redacted preview; no
secrets. Explicit rules in `config.yaml` always win over the cache. Manage
entries in **Settings → Tools** or with
`GET/POST/DELETE /api/permissions/cache`.

### Allowed folders and path expansion

`security.allowed_folders` accepts `~`, `$VAR`, `${VAR}` and Windows-style `%VAR%`.
On Linux, `%USERPROFILE%` is mapped to `$HOME`, so the default
`%USERPROFILE%/Desktop` keeps working without editing the config. Paths are
resolved relative to the project root when they are not absolute.

## Configuration via the web UI

- **General:** language, history, compaction, snapshots.
- **Model:** provider, model, temperature, tokens, timeout, fallback, auto-select, GPU, context.
- **Engine:** preload, watchdog, interval, keep-alive.
- **Memory:** consolidation, min score, timeouts.
- **Network:** internet, local blocking, domains, timeout.
- **Tools:** per-tool permissions and step limit.
- **Downloads:** enable, folder, concurrent, proxy, cookies, ffmpeg.
- **Knowledge:** enable, limits, chunk, top_k, context.
- **Maps:** enable, folder, source build, private hosts, storage/usage and remembered permissions.
- **System:** status, logs, runtime, stop.

Changes via web go through `POST /api/settings` (validates and coerces values) and `POST /api/providers/config` (saves keys to the vault, never to the YAML).

## Common examples

### Use OpenAI provider

```yaml
operation:
  mode: api
  provider: openai
  model: gpt-4o-mini
  base_url: ''
  api_key: '{env:OPENAI_API_KEY}'
```

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

```bash
export OPENAI_API_KEY="sk-..."
```

### Use remote Ollama (LAN)

```yaml
operation:
  mode: local
  provider: ollama
  base_url: http://192.168.0.50:11434
  model: llama3.2:3b
```

### Disable internet

```yaml
network:
  allow_internet_access: false
```

### Reset memory (careful)

Delete the contents of `data/vector_db/` and `data/lessons/` — but back up first.
The independent knowledge base lives in `data/knowledge_db/`.

## Verification and troubleshooting

```powershell
# Windows
python -c "import yaml; print(yaml.safe_load(open(r'F:\config\config.yaml')))"
python -c "import sys; sys.path.insert(0,r'F:\'); import core.secrets as s; print(s.list_secret_names())"
Test-NetConnection 127.0.0.1 -Port 8000
Test-NetConnection 127.0.0.1 -Port 11434
Get-Content F:\logs\drix.log -Tail 30
```

```bash
# Linux
.venv/bin/python -c "import yaml; print(yaml.safe_load(open('config/config.yaml')))"
.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import core.secrets as s; print(s.list_secret_names())"
ss -ltnp | grep -E ':(8000|11434)\b'
tail -n 30 logs/drix.log
```

| Symptom | Cause | Fix |
|---------|-------|-----|
| 401 Unauthorized | Wrong/missing key | Check `DRIX_SECURITY_API_KEY` or vault |
| Model does not load | Port 11434 | Restart engine or change `engine.port` |
| Web does not open | Error in `web_app.py` | Check `logs/drix.log`, restart service |
| Download fails | SSRF/network | Allow domain in `allowed_domains` |
| Knowledge base empty | Missing embeddings | Start Ollama and pull `nomic-embed-text` |
| Map extraction fails | `pmtiles` CLI missing | Put `pmtiles`/`pmtiles.exe` in `ia_system/bin/` or `PATH` |
| Map panels disabled | `maps.enabled: false` | Enable in Settings → Maps or `config.yaml` |
| Map download rejected | Private host or `http://` | Use HTTPS or enable `maps.allow_private_hosts` |
| Map opens without tiles | Vendor/glyph assets missing | Restore `ui/front/vendor/` and `ui/front/map-assets/` |
| `409` during map import | Import offset changed | Resume from the returned `offset` (the UI does this) |

---

*Document created from the Drix functional reference on 2026-11-14.*

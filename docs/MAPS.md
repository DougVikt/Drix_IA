# Offline Maps — Drix

> PMTiles + MapLibre GL JS served by Drix itself. Download regions, import local
> files and browse maps without an internet connection.

## Table of contents

- [How it works](#how-it-works)
- [Storage](#storage)
- [Requirements](#requirements)
- [Enabling and settings](#enabling-and-settings)
- [Using the Maps panel](#using-the-maps-panel)
- [Presets](#presets)
- [Chat commands](#chat-commands)
- [Permissions](#permissions)
- [HTTP API](#http-api)
- [Linux notes](#linux-notes)
- [Troubleshooting](#troubleshooting)
- [Licenses and attribution](#licenses-and-attribution)

---

## How it works

Drix serves offline maps from the same FastAPI process used by the web UI. There
is no separate tile server and no cloud dependency after a map is downloaded.

1. The browser loads MapLibre GL JS and the PMTiles JavaScript library from
   `ui/front/vendor/` (local files, no CDN).
2. The style URL `/api/maps/{id}/style.json` describes the local PMTiles source
   and the Drix basemap layers (light/dark theme).
3. MapLibre requests tiles through `/api/maps/{id}/tiles`. Drix answers with
   HTTP Range (`206 Partial Content`), `HEAD`, `ETag` and `304`, reading only
   the requested byte range from the `.pmtiles` file.
4. Glyphs come from `/api/maps/assets/fonts/...` in `ui/front/map-assets/`.

Downloads, extractions and imports run as background jobs persisted in
`data/maps/catalog.sqlite3`. A job survives page reloads; cancelled downloads
keep their `.part` file so they can resume later.

## Storage

```text
data/maps/
├── catalog.sqlite3      # installed maps + jobs + uploads
├── files/               # installed .pmtiles files
└── downloads/           # .part files, temporary extracts and estimates
```

- `maps.dir` defaults to `./data/maps`.
- The path must resolve inside the Drix root. Paths outside it are ignored and
  Drix falls back to `data/maps`.
- `~`, `$VAR`, `${VAR}` and Windows-style `%VAR%` are expanded on both
  platforms. On Linux, `%USERPROFILE%` maps to `$HOME`.
- Map files are not copied to `workspace/` and never touch `data/lessons`,
  `data/vector_db` or `data/mem0`.

## Requirements

| Component | Needed for | Where it goes |
|-----------|------------|---------------|
| `pmtiles` CLI | Creating regional extracts from a preset/bbox | `ia_system/bin/pmtiles` (Linux/macOS) or `ia_system/bin/pmtiles.exe` (Windows), or anywhere on `PATH` |
| MapLibre + PMTiles JS | Viewer | `ui/front/vendor/maplibre/`, `ui/front/vendor/pmtiles/` |
| Noto Sans glyphs | Map labels | `ui/front/map-assets/fonts/` |
| Internet (only while downloading/extracting) | Source PMTiles build | — |

Direct URL downloads and local `.pmtiles` imports do **not** need the `pmtiles`
CLI. Only regional extraction does. Drix looks for the bundled binary first and
then for `pmtiles` on `PATH`.

On Windows the bundled `pmtiles.exe` is used. On Linux, download the official
`pmtiles` binary (Protomaps `go-pmtiles` releases), copy it to
`ia_system/bin/pmtiles` and make it executable:

```bash
chmod +x ia_system/bin/pmtiles
ia_system/bin/pmtiles --help
```

## Enabling and settings

```yaml
maps:
  enabled: true
  dir: ./data/maps
  source_url: https://build.protomaps.com/20261118.pmtiles
  max_parallel_downloads: 1
  allow_private_hosts: false
```

| Key | Meaning |
|-----|---------|
| `enabled` | Turns the Maps panel and map tools on/off. |
| `dir` | Catalog and files directory. Must stay inside the Drix root. |
| `source_url` | PMTiles build used by presets and extraction. Pinned to a known-good build. |
| `max_parallel_downloads` | Reserved for future parallelism. This version runs one download/extraction at a time to protect the portable drive. |
| `allow_private_hosts` | Allows `http://` and private/loopback hosts for URL downloads. Keep it `false` unless you use a local mirror. |

`source_url` can point to another Protomaps build or a mirror, as long as it is
a full-planet `.pmtiles` file compatible with `pmtiles extract`.

The same values are available in **Settings → Maps**. Explicit rules in
`config.yaml` always win over decisions remembered in the local permission cache.

## Using the Maps panel

Open **Mapas** in the top bar. The panel has three tabs:

### Installed

Lists name, size, zoom range, coverage and source. Actions:

- **Abrir** — opens the MapLibre viewer; pan/zoom work entirely offline.
- **Apagar** — asks for confirmation, then removes the catalog entry and the
  `.pmtiles` file.

### Download

- Choose one of the 18 Brazil/world presets.
- Drix shows the estimated size and coverage before starting.
- Extraction progress, speed and ETA are updated in the panel.
- **Cancelar** stops the job and keeps the partial file for **Retomar**.
- The panel refreshes automatically while a job is active.

You can also paste a direct `.pmtiles` URL. HTTPS is required by default;
private/loopback hosts and plain HTTP require `maps.allow_private_hosts: true`.
If the server advertises a SHA-256, Drix validates it before adding the map.

### Import

- Select a local `.pmtiles` file.
- The browser sends 4 MB chunks with `PUT`; the server accepts up to 8 MB per
  request.
- If a chunk fails, the frontend retries. On reload, Drix resumes from the
  server-reported offset.
- A wrong offset returns `409` with the current offset.
- **Finish** recalculates SHA-256 on the server; an optional client hash must
  match.
- **Cancel** keeps the `.part` for later. **Discard** removes it
  (`DELETE /api/maps/uploads/{id}?purge=1`).

Confirmations use the browser's native dialog for download, extraction, import
and deletion.

## Presets

Presets live in `config/maps_presets.yaml` and can be edited without touching
Python code. Coordinates are `[min_lon, min_lat, max_lon, max_lat]`.

| Preset | Coverage | Max zoom | Approx. size |
|--------|----------|----------|--------------|
| `mundo-z5` | World | 5 | 15 MB |
| `brasil` | Brazil | 8 | 22 MB |
| `brasil-z10` | Brazil | 10 | 151 MB |
| `sudeste` | Southeast | 10 | 45 MB |
| `nordeste` | Northeast | 10 | — |
| `sul` | South | 10 | — |
| `norte` | North | 10 | — |
| `centro-oeste` | Central-West | 10 | — |
| `sao-paulo` | São Paulo city | 13 | 17 MB |
| `rio-de-janeiro` | Rio de Janeiro city | 13 | — |
| `belo-horizonte` | Belo Horizonte | 13 | — |
| `brasilia` | Brasília | 13 | — |
| `salvador` | Salvador | 13 | — |
| `recife` | Recife | 13 | — |
| `fortaleza` | Fortaleza | 13 | — |
| `porto-alegre` | Porto Alegre | 13 | — |
| `curitiba` | Curitiba | 13 | — |
| `manaus` | Manaus | 13 | — |

Sizes are estimates measured against the pinned build; the actual file can vary
slightly. A z10 Brazil extract is roughly 151 MB; a z13 city extract is much
larger than the estimate for the capital if you expand its bbox.

## Chat commands

Short, unambiguous commands are routed deterministically, without loading the
model and without showing raw JSON:

- `listar mapas` / `mapas instalados` — opens the Installed tab.
- `abrir mapa do Brasil` — opens the viewer for a matching installed map.
- `baixar mapa do Brasil` — opens the Download tab with the preset selected.
- `apagar mapa Brasil` — asks for confirmation before deleting.
- `importar mapa` — opens the Import tab.
- `status dos mapas` — opens the panel and shows active jobs.

The `maps_*` agent tools are also registered for the tool-calling loop:
`maps_list`, `maps_info`, `maps_search`, `maps_open`, `maps_status`,
`maps_download`, `maps_extract`, `maps_delete`.

## Permissions

| Tool | Default | Notes |
|------|---------|-------|
| `maps_list`, `maps_info`, `maps_search`, `maps_open`, `maps_status` | `allow` | Read-only/local |
| `maps_download`, `maps_extract`, `maps_delete` | `ask` | Network/write; always confirmed |

`tools.default_permission` is `ask` for tools without an explicit rule. When a
call is approved with **remember**, the decision is stored outside the project:

- Windows: `%LOCALAPPDATA%\Drix\permissions.json`
- Linux/macOS: `~/.cache/drix/permissions.json` (or `$XDG_CACHE_HOME/drix`)

The cache stores the tool name, a hash of the arguments and a redacted preview;
no secrets are written. Remove entries in **Settings → Tools → Remembered
decisions** or with `DELETE /api/permissions/cache/{key}`. Explicit
`tools.permissions` rules in `config.yaml` always take precedence over the cache.

## HTTP API

All routes require the normal Drix authentication (`X-Drix-Key` or session
cookie). Local map GETs are exempt from the general rate limit because MapLibre
issues many small Range requests while panning.

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/api/maps` | Catalog, presets, jobs, uploads and storage info |
| `GET` | `/api/maps/{id}` | One map |
| `GET` | `/api/maps/{id}/style.json?theme=light\|dark` | Generated MapLibre style |
| `GET`/`HEAD` | `/api/maps/{id}/tiles` | PMTiles bytes, Range/ETag support |
| `DELETE` | `/api/maps/{id}` | Delete catalog entry and file |
| `GET` | `/api/maps/assets/{path}` | Fonts/glyphs |
| `GET` | `/api/maps/jobs` | Recent jobs |
| `GET` | `/api/maps/jobs/{id}` | Job status |
| `POST` | `/api/maps/jobs/{id}/cancel` | Cancel a job |
| `POST` | `/api/maps/jobs/{id}/resume` | Resume a download |
| `POST` | `/api/maps/downloads` | Download a `.pmtiles` URL |
| `POST` | `/api/maps/extract` | Create a preset/bbox extract |
| `POST` | `/api/maps/extract/estimate` | Dry-run size estimate |
| `POST` | `/api/maps/uploads` | Start/resume a chunked import |
| `PUT` | `/api/maps/uploads/{id}?offset=N` | Append a chunk |
| `POST` | `/api/maps/uploads/{id}/finish` | Validate SHA-256 and install |
| `DELETE` | `/api/maps/uploads/{id}[?purge=1]` | Cancel; purge removes the `.part` |

## Linux notes

- Use `start.sh`; it prefers `.venv/bin/python` and sets `OLLAMA_MODELS`,
  `PYTHONUTF8` and `PATH` for the bundled binaries.
- The map stack itself is pure Python/JavaScript and works on Linux. Only the
  extractor binary is platform-specific: use `ia_system/bin/pmtiles` (no
  `.exe`). `scripts/install_linux.sh` marks it executable if present, but does
  not download it.
- `maps.dir` accepts `~`, `$HOME` and `%USERPROFILE%`-style values. The resolved
  path must remain inside the project root (external drives can be mounted
  inside it, e.g. `data/maps` as a symlink).
- Paths are case-sensitive on Linux: keep `ui/front/vendor/` and
  `ui/front/map-assets/` exactly as shipped.
- The viewer uses WebGL. On a headless server, use the web UI from another
  machine; the server itself does not open a browser in `headless` mode.
- If extraction says `pmtiles não encontrado`, install the Linux binary or put
  it on `PATH`; a `pmtiles.exe` copied from Windows will not run.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Panel says maps are disabled | `maps.enabled: false` | Enable it in Settings → Maps or `config.yaml` |
| `pmtiles não encontrado` | Missing extractor binary | Put `pmtiles`/`pmtiles.exe` in `ia_system/bin/` or `PATH` |
| Extraction fails immediately | `source_url` unreachable or wrong build | Check the URL and network/SSRF settings |
| Download rejected: private host | `allow_private_hosts: false` | Use a public HTTPS URL or enable the toggle for a local mirror |
| `409` during import | Offset changed (reload/retry) | Resume from the returned `offset`; the UI does this automatically |
| `SHA-256 do arquivo não confere` | Corrupted/incomplete upload | Discard the upload and import again |
| Map opens but tiles never load | Vendor assets missing or wrong path | Restore `ui/front/vendor/`; check `/vendor/maplibre/maplibre-gl.js` returns 200 |
| Labels missing | Glyph files missing | Restore `ui/front/map-assets/fonts/` |
| `416` on tiles | Range beyond file size or stale catalog | Reload the map; if it persists, reimport the file |
| Job stuck after a crash | Process died mid-job | Restart Drix; jobs are marked `interrupted` and can be resumed/cancelled |
| Storage full | Large z10/z13 extracts | Delete unused maps or move `maps.dir` to a larger disk inside the project |

## Licenses and attribution

- **MapLibre GL JS** — BSD-3-Clause.
- **PMTiles** — BSD-3-Clause (specification is CC0).
- **Protomaps basemap data/styles** — ODbL for OpenStreetMap-derived data;
  attribution is embedded in the generated style.
- **Noto Sans** — SIL Open Font License 1.1.

Keep the attribution visible when redistributing maps or screenshots of the
viewer.

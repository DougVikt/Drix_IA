"""Native URL media downloader for Drix.

The engine is `yt-dlp` (installed in the project venv), the same tool that
powers most desktop downloaders.  It handles YouTube, Instagram, TikTok, X,
Reddit, Twitch, direct media links and the ~1800 sites yt-dlp supports.

Downloads run in background threads.  The web UI and the chat command only
poll a job table, so neither the HTTP server nor the model loop blocks while
a file is being fetched.  When ffmpeg is missing the downloader still works:
it falls back to progressive formats and keeps the original audio container.
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from . import logs, tools
from . import platform_paths

try:  # yt-dlp is optional: Drix keeps working without it.
    import yt_dlp
except Exception:  # pragma: no cover - only on a broken install
    yt_dlp = None

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DIR = _ROOT / "workspace" / "downloads"

_JOBS: dict[str, dict] = {}
_JOBS_LOCK = threading.Lock()
_MAX_JOBS = 100

_SEM: threading.BoundedSemaphore | None = None
_SEM_LOCK = threading.Lock()
_SEM_SIZE = 0


class _Cancelled(RuntimeError):
    """Raised inside a progress hook to abort a running download."""


# ─── Config helpers ──────────────────────────────────────────────

def _cfg() -> dict:
    try:
        from .main import config
        data = config.raw().get("downloads") or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _setting(name: str, default=None):
    value = _cfg().get(name, default)
    return default if value is None else value


def _expand(path: str) -> Path:
    return platform_paths.expand_path(path, base=_ROOT)


def default_dir() -> Path:
    raw = str(_setting("dir", "") or "").strip()
    return _expand(raw) if raw else _DEFAULT_DIR


def ffmpeg_path() -> str:
    configured = str(_setting("ffmpeg", "") or "").strip()
    if configured:
        candidate = _expand(configured)
        if candidate.exists():
            return str(candidate)
    bundled = platform_paths.ffmpeg_binary()
    if bundled:
        return bundled
    try:
        # imageio-ffmpeg ships a portable binary inside the venv, so the
        # downloader gets merging/MP3 support without touching the PATH.
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return str(exe)
    except Exception:
        pass
    return ""


def _ffmpeg_available() -> bool:
    return bool(ffmpeg_path())


def _js_runtimes() -> dict:
    """Give yt-dlp a JavaScript runtime when Node.js is installed.

    Newer yt-dlp releases need a JS runtime for some YouTube formats; Node is
    already used by the rest of the project, so reuse it instead of asking the
    user to install Deno.
    """
    node = shutil.which("node")
    return {"node": {}} if node else {}


def _semaphore() -> threading.BoundedSemaphore:
    global _SEM, _SEM_SIZE
    try:
        size = max(1, min(4, int(_setting("max_concurrent", 2))))
    except (TypeError, ValueError):
        size = 2
    with _SEM_LOCK:
        if _SEM is None or size != _SEM_SIZE:
            _SEM = threading.BoundedSemaphore(size)
            _SEM_SIZE = size
    return _SEM


def _enabled() -> bool:
    return bool(_setting("enabled", True))


def is_available() -> bool:
    return yt_dlp is not None


def info() -> dict:
    version = ""
    if yt_dlp is not None:
        try:
            version = str(yt_dlp.version.__version__)
        except Exception:
            version = "?"
    active = sum(1 for job in list_jobs(_MAX_JOBS)
                 if job.get("status") in ("queued", "downloading", "processing"))
    return {
        "available": yt_dlp is not None,
        "enabled": _enabled(),
        "engine": f"yt-dlp {version}".strip(),
        "ffmpeg": ffmpeg_path(),
        "dir": str(default_dir()),
        "max_concurrent": _setting("max_concurrent", 2),
        "active": active,
    }


# ─── Job table ───────────────────────────────────────────────────

def _now() -> float:
    return time.time()


def _public(job: dict) -> dict:
    return {key: value for key, value in job.items() if not key.startswith("_")}


def _update(job: dict, **fields) -> None:
    with _JOBS_LOCK:
        job.update(fields)
        job["updated_at"] = _now()


def _prune_locked() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    removable = [
        key for key, job in _JOBS.items()
        if job.get("status") in ("done", "error", "cancelled")
    ]
    removable.sort(key=lambda key: _JOBS[key].get("created_at", 0))
    for key in removable[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(key, None)


def _register(job: dict) -> None:
    with _JOBS_LOCK:
        _JOBS[job["id"]] = job
        _prune_locked()


def public(job: dict | None) -> dict | None:
    return _public(job) if job else None


def status(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id or ""))
        return _public(job) if job else None


def list_jobs(limit: int = 50) -> list[dict]:
    try:
        limit = max(1, min(100, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    with _JOBS_LOCK:
        jobs = [_public(job) for job in _JOBS.values()]
    jobs.sort(key=lambda job: job.get("created_at", 0), reverse=True)
    return jobs[:limit]


def clear_finished() -> int:
    """Remove finished/failed jobs from the in-memory list."""
    with _JOBS_LOCK:
        keys = [
            key for key, job in _JOBS.items()
            if job.get("status") in ("done", "error", "cancelled")
        ]
        for key in keys:
            _JOBS.pop(key, None)
    return len(keys)


def wait(job_id: str, timeout: float = 180.0) -> dict | None:
    """Block until the job finishes or ``timeout`` seconds elapse."""
    deadline = time.time() + max(1.0, float(timeout or 180))
    while time.time() < deadline:
        job = status(job_id)
        if not job or job.get("status") in ("done", "error", "cancelled"):
            return job
        time.sleep(0.4)
    return status(job_id)


def cancel(job_id: str) -> bool:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id or ""))
        if not job:
            return False
        if job.get("status") in ("done", "error", "cancelled"):
            return False
        job["_cancel"].set()
        job["status"] = "cancelling"
        job["updated_at"] = _now()
    return True


# ─── URL validation ──────────────────────────────────────────────

def _validate(url: str) -> str:
    text = str(url or "").strip()
    if len(text) > 4096:
        raise ValueError("URL muito longa.")
    try:
        parts = urlparse(text)
    except ValueError:
        raise ValueError("URL inválida.")
    if parts.scheme not in ("http", "https"):
        raise ValueError("Use um link http:// ou https://.")
    if not parts.hostname:
        raise ValueError("URL inválida.")
    from . import web
    net = web._net_config()
    if not _is_local(parts.hostname) and not _internet_allowed():
        raise ValueError("Acesso à internet está desligado nas configurações.")
    web.check_url(text, net)
    return text


def _is_local(hostname: str) -> bool:
    host = (hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local")


def _internet_allowed() -> bool:
    try:
        from .main import config
        return bool(config.get("network", "allow_internet_access", default=True))
    except Exception:
        return True


# ─── yt-dlp plumbing ─────────────────────────────────────────────

class _YTLogger:
    """Route yt-dlp messages to the project log without ANSI noise."""

    def debug(self, msg):
        return

    def info(self, msg):
        return

    @staticmethod
    def _clean(msg) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", str(msg or "")).strip()

    @staticmethod
    def _noise(text: str) -> bool:
        # yt-dlp warns about Python 3.10 on every run; the download still
        # works, so keep the log focused on real problems.
        return text.lower().startswith("deprecated feature")

    def warning(self, msg):
        text = self._clean(msg)
        if text and not self._noise(text):
            logs.warn(f"DOWNLOAD {text[:300]}")

    def error(self, msg):
        text = self._clean(msg)
        if text and not self._noise(text):
            logs.warn(f"DOWNLOAD error {text[:300]}")


def _format_selector(quality, audio_only: bool, ffmpeg: bool) -> str:
    height = ""
    try:
        h = int(quality)
        if 144 <= h <= 2160:
            height = f"[height<={h}]"
    except (TypeError, ValueError):
        height = ""

    if audio_only:
        return "bestaudio[ext=m4a]/bestaudio/best" if not ffmpeg else "bestaudio/best"

    if ffmpeg:
        # yt-dlp merges the best video with the best audio.
        return (
            f"bv*{height}+ba/b{height}/bv*+ba/b"
            if height else "bv*+ba/b"
        )
    # No ffmpeg: only single-file (progressive) formats can be used.
    return (
        f"b{height}[ext=mp4]/b{height}/b[ext=mp4]/b"
        if height else "b[ext=mp4]/b"
    )


def _options(job: dict) -> dict:
    ffmpeg = ffmpeg_path()
    has_ffmpeg = bool(ffmpeg)
    audio_only = bool(job.get("audio_only"))
    opts = {
        "outtmpl": str(Path(job["dir"]) / "%(title).120B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "playlistend": 1,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "windowsfilenames": True,
        "overwrites": False,
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
        "format": _format_selector(job.get("quality"), audio_only, has_ffmpeg),
        "progress_hooks": [lambda data: _progress_hook(job, data)],
        "postprocessor_hooks": [lambda data: _postprocessor_hook(job, data)],
        "logger": _YTLogger(),
    }
    runtimes = _js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if has_ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
        if not audio_only:
            opts["merge_output_format"] = "mp4"
    if audio_only and has_ffmpeg:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    proxy = str(_setting("proxy", "") or "").strip()
    if proxy:
        opts["proxy"] = proxy
    cookies = str(_setting("cookies", "") or "").strip()
    if cookies:
        path = _expand(cookies)
        if path.exists():
            opts["cookiefile"] = str(path)
    return opts


def _clean_text(value, limit: int = 300) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(value or ""))
    text = " ".join(text.split())
    return text[:limit]


def _progress_hook(job: dict, data: dict) -> None:
    if job["_cancel"].is_set():
        raise _Cancelled("cancelado pelo usuário")

    state = data.get("status")
    if state == "downloading":
        temp = str(data.get("tmpfilename") or "").strip()
        if temp:
            job["_partials"].add(temp)
        downloaded = int(data.get("downloaded_bytes") or 0)
        total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
        percent = round(downloaded * 100.0 / total, 1) if total else 0.0
        _update(
            job,
            status="downloading",
            progress=min(99.0, percent),
            downloaded_bytes=downloaded,
            total_bytes=total,
            speed=data.get("speed"),
            eta=data.get("eta"),
            filename=Path(str(data.get("filename") or "")).name,
            error="",
        )
    elif state == "finished":
        _update(job, status="processing", progress=100.0, speed=None, eta=0)


def _postprocessor_hook(job: dict, data: dict) -> None:
    if job["_cancel"].is_set():
        raise _Cancelled("cancelado pelo usuário")
    if data.get("status") in ("started", "processing"):
        _update(job, status="processing", progress=100.0)


def _first_entry(info: dict) -> dict:
    if not isinstance(info, dict):
        return {}
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if entry:
                return entry
    return info


def _final_path(info: dict, job: dict) -> str:
    candidates: list[str] = []
    for item in info.get("requested_downloads") or []:
        for key in ("filepath", "filename", "_filename"):
            value = item.get(key)
            if value:
                candidates.append(str(value))
    for key in ("filepath", "_filename", "filename"):
        value = info.get(key)
        if value:
            candidates.append(str(value))

    stems: list[str] = []
    for value in candidates:
        try:
            stems.append(str(Path(value).with_suffix("")))
        except Exception:
            continue

    if job.get("audio_only") and _ffmpeg_available():
        candidates = [stem + ".mp3" for stem in stems] + candidates

    for value in candidates:
        if value and Path(value).exists():
            return str(Path(value))

    # Postprocessors may rename the file after the hooks ran: look for the
    # newest file that starts with the expected stem.
    for stem in stems[:3]:
        folder = Path(stem).parent
        base = Path(stem).name
        try:
            matches = sorted(
                folder.glob(base + ".*"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            matches = []
        if matches:
            return str(matches[0])
    return ""


def _download(job: dict) -> None:
    opts = _options(job)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = _first_entry(ydl.extract_info(job["url"], download=True) or {})
        title = str(info.get("title") or "").strip()
        path = _final_path(info, job)
        size = 0
        if path:
            try:
                size = Path(path).stat().st_size
            except Exception:
                size = 0
        _update(
            job,
            status="done",
            progress=100.0,
            title=title or job.get("title") or "",
            filepath=path,
            filename=Path(path).name if path else job.get("filename", ""),
            bytes=size,
            speed=None,
            eta=0,
            error="",
        )


def _cleanup_partials(job: dict) -> None:
    """Remove temporary fragments left behind by a cancelled/failed job."""
    try:
        base = Path(job.get("dir") or default_dir()).resolve()
    except Exception:
        base = None
    for raw in list(job.get("_partials") or []):
        try:
            path = Path(raw)
            if not path.is_absolute():
                path = base / path if base else path
            resolved = path.resolve()
            if base is not None and base not in resolved.parents:
                continue
            if resolved.is_file():
                resolved.unlink()
        except Exception:
            pass
    job["_partials"].clear()


def _run(job: dict) -> None:
    try:
        with _semaphore():
            if job["_cancel"].is_set():
                raise _Cancelled("cancelado pelo usuário")
            _update(job, status="downloading")
            _download(job)
    except _Cancelled:
        _update(job, status="cancelled", speed=None, eta=0,
                error="Cancelado pelo usuário.")
    except Exception as exc:
        message = _clean_text(exc, 500) or "erro desconhecido"
        _update(job, status="error", speed=None, eta=0, error=message)
        logs.warn(f"DOWNLOAD failed id={job['id']} url={job['url'][:200]!r}: {message}")
    finally:
        if job.get("status") in ("cancelled", "error"):
            _cleanup_partials(job)


# ─── Public API ──────────────────────────────────────────────────

def start(url: str, *, quality=None, audio_only: bool = False,
          workspace: str = "default", directory=None) -> dict:
    if not _enabled():
        raise ValueError("Downloads estão desligados nas configurações.")
    if yt_dlp is None:
        raise ValueError("yt-dlp não está instalado no ambiente da Drix.")
    clean_url = _validate(url)

    folder = _expand(directory) if directory else default_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise ValueError(f"Não foi possível criar a pasta de downloads: {exc}")

    job = {
        "id": uuid.uuid4().hex[:10],
        "url": clean_url,
        "title": "",
        "status": "queued",
        "progress": 0.0,
        "downloaded_bytes": 0,
        "total_bytes": 0,
        "bytes": 0,
        "speed": None,
        "eta": None,
        "filename": "",
        "filepath": "",
        "error": "",
        "quality": quality or None,
        "audio_only": bool(audio_only),
        "workspace": str(workspace or "default"),
        "dir": str(folder),
        "created_at": _now(),
        "updated_at": _now(),
        "_cancel": threading.Event(),
        "_partials": set(),
    }
    _register(job)
    thread = threading.Thread(
        target=_run, args=(job,), daemon=True, name=f"drix-download-{job['id']}"
    )
    thread.start()
    return _public(job)


def probe(url: str) -> dict:
    if yt_dlp is None:
        raise ValueError("yt-dlp não está instalado no ambiente da Drix.")
    clean_url = _validate(url)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "playlistend": 1,
        "socket_timeout": 20,
        "logger": _YTLogger(),
    }
    runtimes = _js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = _first_entry(ydl.extract_info(clean_url, download=False) or {})

    formats = []
    for item in info.get("formats") or []:
        height = item.get("height")
        formats.append({
            "id": item.get("format_id"),
            "ext": item.get("ext"),
            "height": height,
            "fps": item.get("fps"),
            "filesize": item.get("filesize") or item.get("filesize_approx"),
            "vcodec": item.get("vcodec"),
            "acodec": item.get("acodec"),
            "note": item.get("format_note"),
        })
    formats.sort(key=lambda f: (f["height"] or 0, f["filesize"] or 0), reverse=True)

    return {
        "url": clean_url,
        "title": info.get("title") or "",
        "duration": info.get("duration"),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "thumbnail": info.get("thumbnail") or "",
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
        "is_live": bool(info.get("is_live")),
        "webpage_url": info.get("webpage_url") or clean_url,
        "formats": formats[:30],
    }


# ─── Text helpers (tools + chat) ─────────────────────────────────

def format_bytes(value) -> str:
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return f"{size:.1f} {units[index]}"


def format_speed(value) -> str:
    text = format_bytes(value)
    return f"{text}/s" if text else ""


def format_eta(value) -> str:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}min {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}min"


def describe(job: dict | None) -> str:
    if not job:
        return "Download não encontrado."
    state = job.get("status")
    title = job.get("title") or job.get("filename") or job.get("url") or ""
    if state == "queued":
        return f"Na fila: {title}"
    if state == "downloading":
        parts = [f"{job.get('progress', 0):.0f}%"]
        speed = format_speed(job.get("speed"))
        if speed:
            parts.append(speed)
        eta = format_eta(job.get("eta"))
        if eta:
            parts.append(f"faltam {eta}")
        return f"Baixando: {title} — " + " · ".join(parts)
    if state == "processing":
        return f"Processando: {title}"
    if state == "cancelling":
        return f"Cancelando: {title}"
    if state == "done":
        path = job.get("filepath") or job.get("filename") or ""
        size = format_bytes(job.get("bytes"))
        suffix = f" ({size})" if size else ""
        return f"Concluído: {path}{suffix}"
    if state == "cancelled":
        return f"Cancelado: {title}"
    return f"Falhou: {title} — {job.get('error') or 'erro desconhecido'}"


# ─── Agent tools ─────────────────────────────────────────────────

def _tool_download(args: dict, ctx) -> str:
    quality = args.get("quality")
    try:
        quality = int(quality) if quality not in (None, "") else None
    except (TypeError, ValueError):
        quality = None
    job = start(
        str(args.get("url") or ""),
        quality=quality,
        audio_only=bool(args.get("audio_only")),
        workspace=getattr(ctx, "workspace", "default"),
    )
    if args.get("wait"):
        try:
            timeout = float(args.get("timeout") or 180)
        except (TypeError, ValueError):
            timeout = 180.0
        job = wait(job["id"], timeout=min(max(timeout, 5.0), 900.0)) or job
    return f"id={job['id']} · {describe(job)}"


def _tool_info(args: dict, ctx) -> str:
    data = probe(str(args.get("url") or ""))
    lines = [f"Título: {data['title']}"]
    if data.get("uploader"):
        lines.append(f"Canal: {data['uploader']}")
    if data.get("duration"):
        lines.append(f"Duração: {format_eta(data['duration'])}")
    if data.get("extractor"):
        lines.append(f"Fonte: {data['extractor']}")
    if data.get("is_live"):
        lines.append("Ao vivo: sim")
    heights = sorted({f["height"] for f in data["formats"] if f.get("height")})
    if heights:
        lines.append("Resoluções: " + ", ".join(f"{h}p" for h in heights[-8:]))
    lines.append(f"Link: {data['webpage_url']}")
    return "\n".join(lines)


def _tool_status(args: dict, ctx) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if job_id:
        return describe(status(job_id))
    return _tool_list(args, ctx)


def _tool_list(args: dict, ctx) -> str:
    try:
        limit = int(args.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    jobs = list_jobs(limit=limit)
    if not jobs:
        return "Nenhum download recente."
    return "\n".join(f"{job['id']} · {job['status']} · {describe(job)}" for job in jobs)


def _tool_cancel(args: dict, ctx) -> str:
    job_id = str(args.get("job_id") or "").strip()
    if not job_id:
        raise ValueError("job_id é obrigatório")
    return "Cancelamento solicitado." if cancel(job_id) else "Download não encontrado ou já finalizado."


tools.register(tools.Tool(
    "download_media",
    "Baixa vídeo ou áudio de um link (YouTube, Instagram, TikTok, X, Reddit, "
    "Twitch e links diretos) para a pasta de downloads da Drix.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Link http/https da mídia"},
            "quality": {"type": "integer", "description": "Altura máxima, ex.: 720 ou 1080"},
            "audio_only": {"type": "boolean", "description": "Baixar somente o áudio"},
            "wait": {"type": "boolean", "description": "Aguardar o fim antes de responder"},
            "timeout": {"type": "integer", "description": "Segundos de espera quando wait=true"},
        },
        "required": ["url"],
    },
    _tool_download,
    danger="write",
))

tools.register(tools.Tool(
    "download_info",
    "Mostra título, canal, duração e resoluções de um link, sem baixar.",
    {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    _tool_info,
    danger="network",
))

tools.register(tools.Tool(
    "download_status",
    "Mostra o progresso de um download pelo id.",
    {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
    _tool_status,
))

tools.register(tools.Tool(
    "download_list",
    "Lista os downloads recentes da Drix.",
    {
        "type": "object",
        "properties": {"limit": {"type": "integer"}},
    },
    _tool_list,
))

tools.register(tools.Tool(
    "download_cancel",
    "Cancela um download em andamento.",
    {
        "type": "object",
        "properties": {"job_id": {"type": "string"}},
        "required": ["job_id"],
    },
    _tool_cancel,
    danger="write",
))

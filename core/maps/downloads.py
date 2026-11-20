"""Downloads, importação em partes e extrações de mapas.

Um único job de rede por vez, como o restante da Drix. Os arquivos parciais
ficam em ``data/maps/downloads`` e podem ser retomados com HTTP Range.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from . import extract, store

ROOT = Path(__file__).resolve().parents[2]
_LOCK = threading.RLock()
_ACTIVE: dict[str, threading.Event] = {}
_INIT_PATH = ""
_CHUNK = 4 * 1024 * 1024

_FIELDS = {
    "status", "bytes_done", "bytes_total", "speed", "error", "map_id",
    "filename", "name", "url", "meta",
}


class OffsetError(Exception):
    def __init__(self, current: int):
        super().__init__(f"offset incorreto; o servidor está em {current}")
        self.current = int(current)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cfg() -> dict:
    try:
        from core.main import config
        return config.raw().get("maps", {}) or {}
    except Exception:
        return {}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(store.db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    global _INIT_PATH
    path = str(store.db_path())
    if _INIT_PATH == path:
        return
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                name TEXT DEFAULT '',
                url TEXT DEFAULT '',
                filename TEXT DEFAULT '',
                status TEXT NOT NULL,
                bytes_done INTEGER DEFAULT 0,
                bytes_total INTEGER DEFAULT 0,
                speed REAL DEFAULT 0,
                error TEXT DEFAULT '',
                map_id TEXT DEFAULT '',
                meta TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute(
            "UPDATE jobs SET status='interrupted', speed=0, updated_at=? "
            "WHERE status IN ('queued','running','verifying','saving','cancelling','uploading')",
            (_now(),),
        )
    _INIT_PATH = path


def _job(row) -> dict:
    if row is None:
        return {}
    data = dict(row)
    try:
        data["meta"] = json.loads(data.get("meta") or "{}")
    except Exception:
        data["meta"] = {}
    total = int(data.get("bytes_total") or 0)
    done = int(data.get("bytes_done") or 0)
    data["progress"] = round(done * 100.0 / total, 1) if total else 0.0
    data["size_label"] = store.human_size(total) if total else store.human_size(done)
    speed = float(data.get("speed") or 0)
    data["speed_label"] = (store.human_size(speed) + "/s") if speed > 0 else ""
    if total and speed > 0:
        data["eta_label"] = _eta((total - done) / speed)
    else:
        data["eta_label"] = ""
    data["active"] = data.get("status") in {
        "queued", "running", "verifying", "saving", "cancelling",
    }
    return data


def _eta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}min"
    return f"{seconds // 3600}h"


def get_job(job_id: str) -> dict:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
    return _job(row)


def list_jobs(limit: int = 50) -> list[dict]:
    init()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_job(row) for row in rows]


def _create_job(kind: str, name: str, *, url: str = "", filename: str = "",
                total: int = 0, meta: dict | None = None) -> dict:
    init()
    job_id = uuid.uuid4().hex[:12]
    now = _now()
    with _LOCK, _connect() as conn:
        conn.execute("""
            INSERT INTO jobs (
                id, kind, name, url, filename, status, bytes_done,
                bytes_total, speed, error, map_id, meta, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, 0, '', '', ?, ?, ?)
        """, (
            job_id, kind, str(name or ""), str(url or ""), str(filename or ""),
            int(total or 0), json.dumps(meta or {}, ensure_ascii=False), now, now,
        ))
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _job(row)


def update_job(job_id: str, **fields) -> dict:
    init()
    clean = {key: value for key, value in fields.items() if key in _FIELDS}
    if not clean:
        return get_job(job_id)
    clean["updated_at"] = _now()
    with _LOCK, _connect() as conn:
        columns = ", ".join(f"{key} = ?" for key in clean)
        conn.execute(
            f"UPDATE jobs SET {columns} WHERE id = ?",
            tuple(clean.values()) + (str(job_id),),
        )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (str(job_id),)).fetchone()
    return _job(row)


def _ensure_idle() -> None:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE kind IN ('download','extract') "
            "AND status IN ('queued','running','verifying','saving','cancelling') LIMIT 1"
        ).fetchone()
    if row:
        raise RuntimeError("já existe um download ou extração em andamento")


def _start(job_id: str, worker, args: tuple) -> None:
    event = threading.Event()
    with _LOCK:
        _ACTIVE[job_id] = event

    def runner():
        try:
            update_job(job_id, status="running")
            worker(job_id, event, *args)
        except Exception as exc:
            if event.is_set():
                update_job(job_id, status="cancelled", speed=0)
            else:
                update_job(job_id, status="error", error=str(exc)[:500], speed=0)
        finally:
            with _LOCK:
                _ACTIVE.pop(job_id, None)

    threading.Thread(target=runner, daemon=True, name=f"maps-{job_id}").start()


def _validate_url(url: str, allow_private: bool = False) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("use um link https://")
    if parsed.scheme == "http" and not allow_private:
        raise ValueError("links http só são aceitos para hosts privados habilitados")
    host = parsed.hostname
    if not host:
        raise ValueError("link sem host")
    if not allow_private and host.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("host local bloqueado")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"não foi possível resolver o host: {exc}")
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            if not allow_private:
                raise ValueError("host privado bloqueado (habilite em Configurações → Mapas)")
    return text


def _display_name(url: str, name: str) -> str:
    base = str(name or "").strip()
    if not base:
        base = Path(urlparse(url).path).name or "Mapa"
    base = re.sub(r"\.pmtiles$", "", base, flags=re.I)
    base = re.sub(r"[^A-Za-z0-9À-ÿ ._-]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return (base or "Mapa")[:80]


_MAX_REDIRECTS = 8


@contextmanager
def _stream_get(client: httpx.Client, url: str, headers: dict, allow_private: bool):
    """Abre um GET em streaming validando cada destino antes de requisitar.

    O ``httpx`` com ``follow_redirects=True`` conecta ao host de destino antes
    de qualquer validação, o que permitiria SSRF via redirect. Aqui os saltos
    são seguidos manualmente: o próximo host só é acessado depois de passar por
    ``_validate_url``.
    """
    current = _validate_url(url, allow_private)
    for _ in range(_MAX_REDIRECTS + 1):
        request = client.build_request("GET", current, headers=headers)
        response = client.send(request, stream=True)
        if response.is_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise RuntimeError("redirecionamento sem destino")
            current = _validate_url(urljoin(current, location), allow_private)
            continue
        try:
            yield response
        finally:
            response.close()
        return
    raise RuntimeError("redirecionamentos demais")


def _download_worker(job_id: str, event: threading.Event, url: str,
                     name: str, expected_sha256: str, allow_private: bool) -> None:
    part = store.downloads_dir() / f"{job_id}.part"
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "Drix/1.0 (+offline maps)"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    timeout = httpx.Timeout(30.0, read=90.0)
    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        with _stream_get(client, url, headers, allow_private) as response:
            if response.status_code == 416 and offset:
                raise RuntimeError("o arquivo parcial não corresponde mais ao servidor; cancele e baixe de novo")
            if response.status_code not in (200, 206):
                raise RuntimeError(f"servidor respondeu HTTP {response.status_code}")
            ctype = (response.headers.get("content-type") or "").lower()
            if "text/html" in ctype:
                raise RuntimeError("o link devolveu uma página HTML, não um PMTiles")
            if offset and response.status_code == 200:
                offset = 0
                part.unlink(missing_ok=True)
            length = int(response.headers.get("content-length") or 0)
            total = length + offset if response.status_code == 206 else length
            mode = "ab" if offset else "wb"
            digest = hashlib.sha256() if not offset else None
            done = offset
            last_time = time.time()
            last_bytes = done
            update_job(job_id, bytes_done=done, bytes_total=total, filename=name, status="running")
            with open(part, mode) as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    if event.is_set():
                        update_job(job_id, status="cancelled", speed=0)
                        return
                    handle.write(chunk)
                    done += len(chunk)
                    if digest is not None:
                        digest.update(chunk)
                    now = time.time()
                    if now - last_time >= 0.5:
                        speed = (done - last_bytes) / max(0.001, now - last_time)
                        last_time, last_bytes = now, done
                        update_job(job_id, bytes_done=done, bytes_total=total, speed=speed)
                handle.flush()
                os.fsync(handle.fileno())
    if event.is_set():
        update_job(job_id, status="cancelled", speed=0)
        return
    if total and done != total:
        raise RuntimeError(f"download incompleto: {done} de {total} bytes")
    if digest is None:
        update_job(job_id, status="verifying", speed=0)
        digest = store.sha256_file(part)
    else:
        digest = digest.hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise RuntimeError("SHA-256 do arquivo não confere")
    update_job(job_id, status="saving", bytes_done=done, bytes_total=total, speed=0)
    attribution = "© OpenStreetMap contributors · Protomaps" if "protomaps" in url.lower() else ""
    license_name = "ODbL" if "protomaps" in url.lower() else ""
    item = store.add_map(
        part, name, source_url=url, license=license_name,
        attribution=attribution, sha256=digest,
    )
    update_job(
        job_id, status="done", map_id=item["id"], name=item["name"],
        bytes_done=item["size_bytes"], bytes_total=item["size_bytes"], speed=0,
    )


def start_download(url: str, name: str = "", expected_sha256: str = "") -> dict:
    cfg = _cfg()
    if not cfg.get("enabled", True):
        raise RuntimeError("mapas estão desativados em config.yaml (maps.enabled=false)")
    allow_private = bool(cfg.get("allow_private_hosts", False))
    url = _validate_url(url, allow_private)
    _ensure_idle()
    display = _display_name(url, name)
    job = _create_job("download", display, url=url, filename=display + ".pmtiles")
    _start(job["id"], _download_worker, (url, display, expected_sha256, allow_private))
    return get_job(job["id"])


def cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError("job não encontrado")
    with _LOCK:
        event = _ACTIVE.get(job_id)
    if event:
        event.set()
        update_job(job_id, status="cancelling", speed=0)
    elif job.get("status") in {"queued", "uploading", "ready"}:
        update_job(job_id, status="cancelled", speed=0)
    return get_job(job_id)


def resume(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError("job não encontrado")
    if job.get("kind") != "download":
        raise RuntimeError("apenas downloads podem ser retomados")
    if job.get("status") not in {"cancelled", "error", "interrupted"}:
        raise RuntimeError("este job não está pausado")
    part = store.downloads_dir() / f"{job_id}.part"
    if not part.exists() or part.stat().st_size <= 0:
        raise RuntimeError("não há arquivo parcial para retomar")
    _ensure_idle()
    cfg = _cfg()
    update_job(job_id, status="queued", error="", speed=0)
    _start(job_id, _download_worker, (
        job.get("url", ""), job.get("name") or "Mapa", "",
        bool(cfg.get("allow_private_hosts", False)),
    ))
    return get_job(job_id)


def _extract_worker(job_id: str, event: threading.Event, source: str,
                    bbox, maxzoom: int, name: str, output: Path) -> None:
    cmd = extract.build_command(source, output, bbox=bbox, maxzoom=maxzoom)
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    buffer = ""
    try:
        while True:
            if event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    proc.kill()
                output.unlink(missing_ok=True)
                update_job(job_id, status="cancelled", speed=0)
                return
            chunk = proc.stdout.read(4096) if proc.stdout else b""
            if not chunk:
                if proc.poll() is not None:
                    break
                continue
            buffer = (buffer + chunk.decode("utf-8", "replace"))[-8192:]
            matches = re.findall(r"\((\d+)/(\d+)\s*MB", buffer)
            if matches:
                done_mb, total_mb = matches[-1]
                update_job(
                    job_id, bytes_done=int(done_mb) * 1000 ** 2,
                    bytes_total=int(total_mb) * 1000 ** 2, status="running",
                )
        code = proc.wait()
        if code != 0:
            tail = buffer.strip().splitlines()[-1] if buffer.strip() else f"código {code}"
            raise RuntimeError(f"pmtiles falhou: {tail}")
        if not output.is_file() or output.stat().st_size <= 0:
            raise RuntimeError("o recorte não gerou arquivo")
        item = store.add_map(
            output, name, source_url=source, license="ODbL",
            attribution="© OpenStreetMap contributors · Protomaps",
        )
        update_job(
            job_id, status="done", map_id=item["id"], name=item["name"],
            bytes_done=item["size_bytes"], bytes_total=item["size_bytes"], speed=0,
        )
    finally:
        if proc.poll() is None:
            proc.kill()
        # Em caso de sucesso add_map já moveu o arquivo; em erro/cancelamento
        # removemos o recorte parcial para não deixar lixo em downloads.
        if output.exists():
            output.unlink(missing_ok=True)


def start_extract(preset: str = "", maxzoom=None, bbox=None, name: str = "",
                  source_url: str = "") -> dict:
    cfg = _cfg()
    if not cfg.get("enabled", True):
        raise RuntimeError("mapas estão desativados em config.yaml (maps.enabled=false)")
    item = extract.get_preset(preset) if preset else {}
    if not item:
        if not bbox:
            raise ValueError("preset de mapa desconhecido")
        item = {
            "name": name or "Recorte personalizado",
            "bbox": extract.validate_bbox(bbox),
            "maxzoom": maxzoom if maxzoom is not None else 8,
            "source_url": source_url or extract.default_source(),
        }
    bbox = item.get("bbox")
    zoom = int(maxzoom if maxzoom is not None else item.get("maxzoom", 8))
    if not (0 <= zoom <= 16):
        raise ValueError("zoom deve ficar entre 0 e 16")
    source = item.get("source_url") or extract.default_source()
    _ensure_idle()
    job = _create_job(
        "extract", item.get("name") or preset, url=source,
        filename=(item.get("name") or preset) + ".pmtiles",
        meta={"preset": preset, "bbox": bbox, "maxzoom": zoom},
    )
    output = store.downloads_dir() / f"{job['id']}.pmtiles"
    _start(job["id"], _extract_worker, (source, bbox, zoom, item.get("name") or preset, output))
    return get_job(job["id"])


def _upload_part(upload_id: str) -> Path:
    return store.downloads_dir() / f"{upload_id}.part"


def _upload_session(job: dict) -> dict:
    part = _upload_part(job["id"])
    offset = part.stat().st_size if part.exists() else 0
    return {
        "upload_id": job["id"],
        "filename": job.get("filename") or "",
        "name": job.get("name") or "",
        "offset": offset,
        "size": int(job.get("bytes_total") or 0),
        "chunk_size": _CHUNK,
        "status": job.get("status"),
    }


def start_upload(filename: str, size: int) -> dict:
    init()
    clean = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", str(filename or "")).strip()
    if not clean.lower().endswith(".pmtiles"):
        raise ValueError("envie um arquivo .pmtiles")
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValueError("tamanho inválido")
    if size <= 0:
        raise ValueError("arquivo vazio")
    free = shutil.disk_usage(store.downloads_dir()).free
    if free < size + 64 * 1024 * 1024:
        raise RuntimeError(f"espaço insuficiente: livre {store.human_size(free)}")
    with _LOCK, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE kind='upload' AND filename=? AND bytes_total=? "
            "AND status IN ('uploading','ready','cancelled','error') "
            "ORDER BY created_at DESC LIMIT 1",
            (clean, size),
        ).fetchone()
    if row:
        job = _job(row)
        part = _upload_part(job["id"])
        if part.exists():
            update_job(job["id"], status="uploading", error="", speed=0)
            return _upload_session(get_job(job["id"]))
    job = _create_job("upload", clean[:-8] if clean.lower().endswith(".pmtiles") else clean,
                      filename=clean, total=size, meta={"size": size})
    _upload_part(job["id"]).touch()
    update_job(job["id"], status="uploading")
    return _upload_session(get_job(job["id"]))


def resume_upload(upload_id: str) -> dict:
    job = get_job(upload_id)
    if not job or job.get("kind") != "upload":
        raise KeyError("importação não encontrada")
    part = _upload_part(upload_id)
    if not part.exists():
        raise RuntimeError("arquivo parcial não encontrado; selecione o arquivo novamente")
    update_job(upload_id, status="uploading", error="")
    return _upload_session(get_job(upload_id))


def append_upload(upload_id: str, offset: int, data: bytes) -> dict:
    job = get_job(upload_id)
    if not job or job.get("kind") != "upload":
        raise KeyError("importação não encontrada")
    if job.get("status") not in {"uploading", "ready"}:
        raise RuntimeError("importação não está ativa")
    part = _upload_part(upload_id)
    current = part.stat().st_size if part.exists() else 0
    if int(offset) != current:
        raise OffsetError(current)
    total = int(job.get("bytes_total") or 0)
    if total and current + len(data) > total:
        raise ValueError("o bloco ultrapassa o tamanho do arquivo")
    with open(part, "ab") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    done = current + len(data)
    status = "ready" if total and done >= total else "uploading"
    return update_job(upload_id, bytes_done=done, status=status, speed=0)


def finish_upload(upload_id: str, name: str = "", sha256: str = "") -> dict:
    job = get_job(upload_id)
    if not job or job.get("kind") != "upload":
        raise KeyError("importação não encontrada")
    part = _upload_part(upload_id)
    if not part.exists():
        raise RuntimeError("arquivo parcial não encontrado")
    total = int(job.get("bytes_total") or 0)
    if total and part.stat().st_size != total:
        raise RuntimeError("o arquivo ainda não foi enviado por completo")
    update_job(upload_id, status="verifying", speed=0)
    try:
        digest = store.sha256_file(part)
        expected = str(sha256 or "").strip().lower()
        if expected and expected != digest.lower():
            raise ValueError("SHA-256 do arquivo não confere")
        item = store.add_map(
            part, name or job.get("name") or "Mapa", source_url="importação local",
            license="", attribution="", sha256=digest,
        )
    except Exception as exc:
        update_job(upload_id, status="error", error=str(exc)[:500], speed=0)
        raise
    update_job(
        upload_id, status="done", map_id=item["id"], name=item["name"],
        bytes_done=item["size_bytes"], bytes_total=item["size_bytes"], speed=0,
    )
    return item


def cancel_upload(upload_id: str, purge: bool = False) -> dict:
    job = get_job(upload_id)
    if not job or job.get("kind") != "upload":
        raise KeyError("importação não encontrada")
    if purge:
        _upload_part(upload_id).unlink(missing_ok=True)
    update_job(upload_id, status="cancelled", speed=0, error="")
    return get_job(upload_id)


def list_uploads() -> list[dict]:
    init()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE kind='upload' "
            "AND status IN ('uploading','ready','cancelled','error') "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    out = []
    for row in rows:
        job = _job(row)
        if _upload_part(job["id"]).exists():
            out.append(_upload_session(job))
    return out


def shutdown() -> None:
    with _LOCK:
        events = list(_ACTIVE.values())
    for event in events:
        event.set()
    if events:
        time.sleep(0.4)
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status='interrupted', speed=0, updated_at=? "
            "WHERE status IN ('running','queued','verifying','saving','cancelling')",
            (_now(),),
        )

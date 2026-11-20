"""Catálogo local de mapas PMTiles.

Os arquivos ficam em ``data/maps/files`` e o catálogo em
``data/maps/catalog.sqlite3``. Nada aqui toca nas pastas de aprendizagem,
conhecimento ou memória.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import struct
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import platform_paths

ROOT = Path(__file__).resolve().parents[2]
_HEADER_LEN = 127
_LOCK = threading.RLock()


def _cfg() -> dict:
    try:
        from core.main import config
        return config.raw().get("maps", {}) or {}
    except Exception:
        return {}


def settings() -> dict:
    return _cfg()


def _inside_root(path: Path) -> Path:
    path = path.resolve()
    try:
        path.relative_to(ROOT)
        return path
    except ValueError:
        return (ROOT / "data" / "maps").resolve()


def base_dir() -> Path:
    raw = str(_cfg().get("dir") or "./data/maps")
    path = platform_paths.expand_path(raw, base=ROOT)
    return _inside_root(path)


def files_dir() -> Path:
    path = base_dir() / "files"
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    path = base_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    path = base_dir() / "catalog.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    with _LOCK, _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS maps (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                filename TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                minzoom INTEGER,
                maxzoom INTEGER,
                min_lon REAL,
                min_lat REAL,
                max_lon REAL,
                max_lat REAL,
                center_lon REAL,
                center_lat REAL,
                center_zoom INTEGER,
                source_url TEXT DEFAULT '',
                license TEXT DEFAULT '',
                attribution TEXT DEFAULT '',
                sha256 TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_maps_name ON maps(name)")


def human_size(value) -> str:
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str) -> str:
    value = normalize(text)
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return (value or "mapa")[:48]


def read_header(path) -> dict:
    """Lê o cabeçalho PMTiles v3 sem depender do binário pmtiles."""
    path = Path(path)
    with open(path, "rb") as handle:
        raw = handle.read(_HEADER_LEN)
    if len(raw) < _HEADER_LEN or raw[:7] != b"PMTiles":
        raise ValueError("arquivo não é um PMTiles válido")
    if raw[7] != 3:
        raise ValueError(f"versão PMTiles não suportada: {raw[7]}")

    values = struct.unpack_from("<11Q", raw, 8)
    min_lon, min_lat, max_lon, max_lat = struct.unpack_from("<4i", raw, 102)
    center_zoom = raw[118]
    center_lon, center_lat = struct.unpack_from("<2i", raw, 119)
    header = {
        "version": raw[7],
        "root_offset": values[0],
        "root_length": values[1],
        "metadata_offset": values[2],
        "metadata_length": values[3],
        "leaf_offset": values[4],
        "leaf_length": values[5],
        "tile_data_offset": values[6],
        "tile_data_length": values[7],
        "addressed_tiles": values[8],
        "tile_entries": values[9],
        "tile_contents": values[10],
        "clustered": bool(raw[96]),
        "internal_compression": raw[97],
        "tile_compression": raw[98],
        "tile_type": raw[99],
        "minzoom": raw[100],
        "maxzoom": raw[101],
        "min_lon": min_lon / 1e7,
        "min_lat": min_lat / 1e7,
        "max_lon": max_lon / 1e7,
        "max_lat": max_lat / 1e7,
        "center_zoom": center_zoom,
        "center_lon": center_lon / 1e7,
        "center_lat": center_lat / 1e7,
    }
    if not (0 <= header["minzoom"] <= header["maxzoom"] <= 24):
        raise ValueError("faixa de zoom inválida no PMTiles")
    if not (-180 <= header["min_lon"] <= 180 and -180 <= header["max_lon"] <= 180):
        raise ValueError("limites de longitude inválidos no PMTiles")
    if not (-90 <= header["min_lat"] <= 90 and -90 <= header["max_lat"] <= 90):
        raise ValueError("limites de latitude inválidos no PMTiles")
    return header


def sha256_file(path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _row(row) -> dict:
    if row is None:
        return {}
    data = dict(row)

    def _coord(value, digits=2):
        try:
            return f"{float(value):.{digits}f}"
        except (TypeError, ValueError):
            return "?"

    data["size_label"] = human_size(data.get("size_bytes"))
    data["zoom_label"] = f"z{data.get('minzoom')}–{data.get('maxzoom')}"
    data["bounds_label"] = (
        f"{_coord(data.get('min_lon'))},{_coord(data.get('min_lat'))},"
        f"{_coord(data.get('max_lon'))},{_coord(data.get('max_lat'))}"
    )
    data["center"] = [data.get("center_lon"), data.get("center_lat")]
    return data


def list_maps(limit: int = 200) -> list[dict]:
    init()
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM maps ORDER BY created_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_row(row) for row in rows]


def get_map(map_id: str) -> dict:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM maps WHERE id = ?", (str(map_id),)).fetchone()
    return _row(row)


def find_map(query: str) -> dict:
    query = normalize(query)
    if not query:
        return {}
    maps = list_maps(500)
    for item in maps:
        if normalize(item.get("id", "")) == query:
            return item
    for item in maps:
        if normalize(item.get("name", "")) == query:
            return item
    for item in maps:
        name = normalize(item.get("name", ""))
        if query in name or name in query:
            return item
    words = [word for word in query.split() if len(word) > 3]
    best = {}
    score = 0
    for item in maps:
        name = normalize(item.get("name", ""))
        hits = sum(1 for word in words if word in name)
        if hits > score:
            best, score = item, hits
    return best if score else {}


def _move_into(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve():
        return
    try:
        shutil.move(str(src), str(dest))
    except Exception:
        shutil.copy2(str(src), str(dest))
        src.unlink(missing_ok=True)


def add_map(path, name: str, *, source_url: str = "", license: str = "",
            attribution: str = "", sha256: str = "") -> dict:
    init()
    src = Path(path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"arquivo não encontrado: {src}")
    header = read_header(src)
    digest = sha256 or sha256_file(src)
    size = src.stat().st_size

    with _LOCK, _connect() as conn:
        if digest:
            row = conn.execute("SELECT * FROM maps WHERE sha256 = ?", (digest,)).fetchone()
            if row:
                if src.parent == downloads_dir().resolve():
                    src.unlink(missing_ok=True)
                return _row(row)

        clean_name = re.sub(r"[\x00-\x1f]", "", str(name or "Mapa")).strip()[:80] or "Mapa"
        map_id = f"{slugify(clean_name)}-{uuid.uuid4().hex[:6]}"
        filename = f"{map_id}.pmtiles"
        dest = files_dir() / filename
        _move_into(src, dest)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute("""
            INSERT INTO maps (
                id, name, filename, size_bytes, minzoom, maxzoom,
                min_lon, min_lat, max_lon, max_lat,
                center_lon, center_lat, center_zoom,
                source_url, license, attribution, sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            map_id, clean_name, filename, size,
            header["minzoom"], header["maxzoom"],
            header["min_lon"], header["min_lat"], header["max_lon"], header["max_lat"],
            header["center_lon"], header["center_lat"], header["center_zoom"],
            str(source_url or ""), str(license or ""), str(attribution or ""),
            digest, created,
        ))
        row = conn.execute("SELECT * FROM maps WHERE id = ?", (map_id,)).fetchone()
    return _row(row)


def delete_map(map_id: str) -> bool:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM maps WHERE id = ?", (str(map_id),)).fetchone()
        if not row:
            return False
        filename = str(row["filename"])
        target = (files_dir() / filename).resolve()
        if target.parent != files_dir().resolve():
            raise ValueError("caminho de mapa inválido")
        target.unlink(missing_ok=True)
        conn.execute("DELETE FROM maps WHERE id = ?", (str(map_id),))
    return True


def info() -> dict:
    init()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS total FROM maps").fetchone()
    try:
        free = shutil.disk_usage(base_dir()).free
    except Exception:
        free = 0
    return {
        "count": int(row["count"] or 0),
        "bytes": int(row["total"] or 0),
        "size_label": human_size(row["total"]),
        "free_bytes": int(free),
        "free_label": human_size(free),
        "dir": str(base_dir().relative_to(ROOT)).replace("\\", "/"),
    }


def context_text(limit: int = 8) -> str:
    maps = list_maps(limit)
    if not maps:
        return "Mapas offline: nenhum mapa instalado."
    lines = ["Mapas offline instalados (não invente dados fora desta lista):"]
    for item in maps:
        lines.append(
            f"- {item['name']}: {item['zoom_label']}, {item['size_label']}, "
            f"cobertura {item['bounds_label']}"
        )
    free = info().get("free_label", "")
    if free:
        lines.append(f"Espaço livre no armazenamento: {free}.")
    return "\n".join(lines)

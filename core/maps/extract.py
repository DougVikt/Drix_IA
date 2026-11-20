"""Presets e recortes de mapas com o binário oficial ``pmtiles``."""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

import yaml

from . import store
from .. import platform_paths

ROOT = Path(__file__).resolve().parents[2]
PRESETS_PATH = ROOT / "config" / "maps_presets.yaml"

_DEFAULT_SOURCE = "https://build.protomaps.com/20261118.pmtiles"
_DEFAULT_PRESETS = {
    "source_url": _DEFAULT_SOURCE,
    "presets": {
        "mundo-z5": {
            "name": "Mundo (z0–5)",
            "maxzoom": 5,
            "note": "Amostra leve para uso offline",
        },
        "brasil": {
            "name": "Brasil",
            "bbox": [-74, -34, -34, 6],
            "maxzoom": 8,
            "estimate": "22 MB",
        },
    },
}


def _cfg() -> dict:
    try:
        from core.main import config
        return config.raw().get("maps", {}) or {}
    except Exception:
        return {}


def _load() -> dict:
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return dict(_DEFAULT_PRESETS)


def default_source() -> str:
    return str(_cfg().get("source_url") or _load().get("source_url") or _DEFAULT_SOURCE)


def presets() -> dict:
    data = _load()
    items = data.get("presets") or {}
    return items if isinstance(items, dict) else {}


def presets_list() -> list[dict]:
    out = []
    for key, item in presets().items():
        if not isinstance(item, dict):
            continue
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        out.append({
            "key": key,
            "name": item.get("name") or key,
            "bbox": item.get("bbox"),
            "maxzoom": item.get("maxzoom"),
            "minzoom": item.get("minzoom"),
            "estimate": item.get("estimate") or "",
            "note": item.get("note") or "",
            "aliases": [str(alias) for alias in aliases],
        })
    return out


def get_preset(key: str) -> dict:
    item = presets().get(str(key or ""))
    if not isinstance(item, dict):
        return {}
    data = dict(item)
    data["key"] = key
    data["name"] = data.get("name") or key
    data["source_url"] = data.get("source_url") or default_source()
    return data


def validate_bbox(value) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("bbox deve ter 4 números: min_lon,min_lat,max_lon,max_lat")
    try:
        bbox = [float(item) for item in value]
    except (TypeError, ValueError):
        raise ValueError("bbox inválido")
    min_lon, min_lat, max_lon, max_lat = bbox
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        raise ValueError("longitude fora de -180..180")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise ValueError("latitude fora de -90..90")
    if min_lon >= max_lon or min_lat >= max_lat:
        raise ValueError("bbox invertida")
    return bbox


def build_command(source: str, output: Path, bbox=None, maxzoom=None,
                  minzoom=None, dry_run: bool = False) -> list[str]:
    binary = platform_paths.pmtiles_binary()
    if not binary:
        raise RuntimeError(
            "pmtiles não encontrado; coloque o binário em ia_system/bin/ ou no PATH"
        )
    cmd = [binary, "extract", str(source), str(output)]
    if bbox:
        cmd.append("--bbox=" + ",".join(f"{n:g}" for n in validate_bbox(bbox)))
    if maxzoom is not None:
        cmd.append(f"--maxzoom={int(maxzoom)}")
    if minzoom is not None:
        cmd.append(f"--minzoom={int(minzoom)}")
    cmd.append("--download-threads=4")
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def _size_bytes(label: str) -> int:
    match = re.search(r"([0-9.]+)\s*(B|KB|MB|GB|TB)", label or "", re.I)
    if not match:
        return 0
    units = {"B": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3, "TB": 1000 ** 4}
    try:
        return int(float(match.group(1)) * units.get(match.group(2).upper(), 1))
    except (TypeError, ValueError):
        return 0


def estimate(*, preset: str = "", bbox=None, maxzoom=None, source_url="") -> dict:
    item = get_preset(preset) if preset else {}
    if item:
        bbox = item.get("bbox")
        maxzoom = maxzoom if maxzoom is not None else item.get("maxzoom")
        source_url = source_url or item.get("source_url") or default_source()
        name = item.get("name") or preset
    else:
        name = "Recorte personalizado"
        source_url = source_url or default_source()
    if bbox:
        bbox = validate_bbox(bbox)
    if maxzoom is not None and not (0 <= int(maxzoom) <= 16):
        raise ValueError("zoom deve ficar entre 0 e 16")

    out = store.downloads_dir() / f"estimate-{uuid.uuid4().hex[:8]}.pmtiles"
    cmd = build_command(source_url, out, bbox=bbox, maxzoom=maxzoom, dry_run=True)
    try:
        proc = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=600, text=True, encoding="utf-8", errors="replace",
        )
    finally:
        out.unlink(missing_ok=True)
    output = proc.stdout or ""
    match = re.search(r"archive size of\s+([0-9.]+\s*[KMGT]?B)", output, re.I)
    transferred = re.search(r"Extract transferred\s+([0-9.]+\s*[KMGT]?B)", output, re.I)
    if proc.returncode != 0 or not match:
        detail = output.strip().splitlines()[-1] if output.strip() else f"código {proc.returncode}"
        raise RuntimeError(f"não foi possível estimar: {detail}")
    label = match.group(1).strip()
    return {
        "name": name,
        "bbox": bbox,
        "maxzoom": int(maxzoom) if maxzoom is not None else None,
        "source_url": source_url,
        "bytes": _size_bytes(label),
        "size_label": label,
        "transferred_label": transferred.group(1).strip() if transferred else "",
    }

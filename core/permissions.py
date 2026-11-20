"""Cache local de decisões de permissão.

Regras explícitas no ``config.yaml`` sempre vencem. Este cache só é consultado
quando a permissão efetiva é ``ask`` (inclusive o padrão para ferramentas sem
regra própria). As decisões ficam no computador hospedeiro, fora do projeto:

* Windows: ``%LOCALAPPDATA%\\Drix\\permissions.json``
* Linux/macOS: ``~/.cache/drix/permissions.json``

Nada sensível é gravado: guardamos apenas o nome da ferramenta, o hash dos
argumentos e uma prévia com valores potencialmente secretos mascarados.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.RLock()
_VERSION = 1
_HASH_LEN = 24
_SECRET_HINTS = (
    "token", "secret", "password", "passwd", "senha", "api_key", "apikey",
    "authorization", "cookie", "credential", "private_key",
)


def cache_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Drix"
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "drix"


def cache_path() -> Path:
    return cache_dir() / "permissions.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {"version": _VERSION, "decisions": {}}


def _read() -> dict:
    path = cache_path()
    if not path.is_file():
        return _empty()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    decisions = data.get("decisions")
    if not isinstance(decisions, dict):
        data["decisions"] = {}
    data["version"] = _VERSION
    return data


def _write(data: dict) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _canonical(tool: str, arguments: dict | None) -> str:
    payload = {
        "tool": str(tool or ""),
        "args": arguments or {},
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)


def arguments_hash(tool: str, arguments: dict | None) -> str:
    return hashlib.sha256(_canonical(tool, arguments).encode("utf-8")).hexdigest()[:_HASH_LEN]


def key_for(tool: str, arguments: dict | None) -> str:
    return f"{tool}:{arguments_hash(tool, arguments)}"


def _redact(value, depth: int = 0):
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out = {}
        for key, item in list(value.items())[:40]:
            name = str(key)
            if any(hint in name.lower() for hint in _SECRET_HINTS):
                out[name] = "•••"
            else:
                out[name] = _redact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth + 1) for item in list(value)[:20]]
    if isinstance(value, str):
        return value if len(value) <= 160 else value[:157] + "…"
    return value


def preview(tool: str, arguments: dict | None) -> str:
    try:
        text = json.dumps(_redact(arguments or {}), ensure_ascii=False, default=str)
    except Exception:
        text = "{}"
    text = re.sub(r"\s+", " ", text).strip()
    return f"{tool} {text}"[:240]


def decision_for(tool: str, arguments: dict | None) -> str | None:
    """Return a remembered ``allow``/``deny`` for this exact call, if any."""
    key = key_for(tool, arguments)
    with _LOCK:
        data = _read()
        entry = data["decisions"].get(key)
        if not isinstance(entry, dict):
            return None
        decision = str(entry.get("decision") or "")
        if decision not in {"allow", "deny"}:
            return None
        entry["hits"] = int(entry.get("hits") or 0) + 1
        entry["last_used"] = _now()
        data["decisions"][key] = entry
        try:
            _write(data)
        except Exception:
            pass
        return decision


def remember(tool: str, arguments: dict | None, decision: str) -> dict:
    decision = str(decision or "").lower()
    if decision not in {"allow", "deny"}:
        raise ValueError("decisão deve ser 'allow' ou 'deny'")
    if not str(tool or "").strip():
        raise ValueError("ferramenta obrigatória")
    key = key_for(tool, arguments)
    now = _now()
    with _LOCK:
        data = _read()
        current = data["decisions"].get(key)
        entry = {
            "tool": str(tool),
            "hash": arguments_hash(tool, arguments),
            "decision": decision,
            "preview": preview(tool, arguments),
            "created_at": (current or {}).get("created_at") or now,
            "updated_at": now,
            "hits": int((current or {}).get("hits") or 0),
        }
        data["decisions"][key] = entry
        _write(data)
    return {"key": key, **entry}


def forget(key: str) -> bool:
    key = str(key or "").strip()
    if not key:
        return False
    with _LOCK:
        data = _read()
        if key not in data["decisions"]:
            return False
        del data["decisions"][key]
        _write(data)
    return True


def entries() -> list[dict]:
    with _LOCK:
        data = _read()
    out = []
    for key, entry in data["decisions"].items():
        if not isinstance(entry, dict):
            continue
        out.append({"key": key, **entry})
    out.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return out


def clear() -> int:
    with _LOCK:
        data = _read()
        count = len(data["decisions"])
        data["decisions"] = {}
        _write(data)
    return count

"""Encrypted secret storage for provider credentials.

On Windows the ciphertext is produced by DPAPI (``CryptProtectData``), which
binds it to the current Windows user account.  On other platforms there is no
portable keyring available, so the store falls back to base64 with an explicit
warning -- the file is still kept out of ``config.yaml`` and out of logs.

Secrets live in ``data/secrets.json``::

    {"version": 1,
     "items": {"provider:openai": {"enc": "dpapi", "data": "<base64>"}}}

Public API
----------
set_secret(name, value) -> None
get_secret(name, default="") -> str
delete_secret(name) -> bool
has_secret(name) -> bool
mask(value) -> str
migrate_from_config(cfg) -> bool
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from pathlib import Path

from . import logs

HD_ROOT = Path(__file__).resolve().parent.parent
SECRETS_PATH = HD_ROOT / "data" / "secrets.json"

_ENTROPY = b"drix-secret-store-v1"
_PLACEHOLDERS = {"", "sua_chave_aqui", "your_key_here", "changeme", "none", "null"}

_lock = threading.RLock()
_cache: dict | None = None

# ─── DPAPI (Windows) ─────────────────────────────────────────────

_dpapi_available = False
_crypt32 = None
_kernel32 = None

if os.name == "nt":  # pragma: no cover - platform specific
    try:
        from ctypes import wintypes

        class _DATA_BLOB(ctypes.Structure):
            _fields_ = [
                ("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char)),
            ]

        _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        _crypt32.CryptProtectData.restype = ctypes.c_bool
        _crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), ctypes.c_wchar_p,
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
        _crypt32.CryptUnprotectData.restype = ctypes.c_bool
        _crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
            ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(_DATA_BLOB),
        ]
        _kernel32.LocalFree.restype = ctypes.c_void_p
        _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        _dpapi_available = True
    except Exception as exc:  # pragma: no cover
        logs.warn(f"DPAPI unavailable, falling back to obfuscated secrets: {exc}")
        _dpapi_available = False


def _make_blob(data: bytes):
    buf = ctypes.create_string_buffer(data, max(len(data), 1))
    blob = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _dpapi_protect(data: bytes) -> bytes:  # pragma: no cover - platform specific
    in_blob, _in_buf = _make_blob(data)
    entropy, _ent_buf = _make_blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, ctypes.byref(entropy),
        None, None, 0x1, ctypes.byref(out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptProtectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _dpapi_unprotect(data: bytes) -> bytes:  # pragma: no cover - platform specific
    in_blob, _in_buf = _make_blob(data)
    entropy, _ent_buf = _make_blob(_ENTROPY)
    out = _DATA_BLOB()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(entropy),
        None, None, 0x1, ctypes.byref(out),
    )
    if not ok:
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        _kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


# ─── Store ───────────────────────────────────────────────────────

def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = {"version": 1, "items": {}}
    if SECRETS_PATH.exists():
        try:
            loaded = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception as exc:
            logs.warn(f"Could not read secrets store: {exc}")
    data.setdefault("version", 1)
    data.setdefault("items", {})
    _cache = data
    return data


def _hide_windows(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x2
        FILE_ATTRIBUTE_SYSTEM = 0x4
        # Hidden is enough for "ocultar"; avoid System to reduce side effects.
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def _save() -> None:
    data = _load()
    SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, SECRETS_PATH)
    try:
        os.chmod(SECRETS_PATH, 0o600)
    except Exception:
        pass
    _hide_windows(SECRETS_PATH)


def _encode(value: str) -> dict:
    raw = value.encode("utf-8")
    if _dpapi_available:
        try:
            return {"enc": "dpapi", "data": base64.b64encode(_dpapi_protect(raw)).decode("ascii")}
        except Exception as exc:  # pragma: no cover
            logs.warn(f"DPAPI protect failed, storing obfuscated value: {exc}")
    return {"enc": "b64", "data": base64.b64encode(raw).decode("ascii")}


def _decode(item: dict) -> str:
    try:
        blob = base64.b64decode(item.get("data", ""))
    except Exception:
        return ""
    if item.get("enc") == "dpapi":
        try:
            return _dpapi_unprotect(blob).decode("utf-8")
        except Exception as exc:  # pragma: no cover
            logs.warn(f"Could not decrypt secret: {exc}")
            return ""
    return blob.decode("utf-8", "replace")


def encryption_mode() -> str:
    """Human readable label for the active protection backend."""
    return "dpapi" if _dpapi_available else "base64"


def is_real_secret(value: str | None) -> bool:
    if not value:
        return False
    v = str(value).strip()
    if not v:
        return False
    return v.lower() not in _PLACEHOLDERS


def set_secret(name: str, value: str) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("secret name is required")
    with _lock:
        data = _load()
        if not is_real_secret(value):
            data["items"].pop(name, None)
        else:
            data["items"][name] = _encode(str(value).strip())
        _save()


def get_secret(name: str, default: str = "") -> str:
    with _lock:
        item = _load()["items"].get(name)
        if not item:
            return default
        value = _decode(item)
        return value if value else default


def delete_secret(name: str) -> bool:
    with _lock:
        data = _load()
        existed = data["items"].pop(name, None) is not None
        if existed:
            _save()
        return existed


def has_secret(name: str) -> bool:
    with _lock:
        return bool(_load()["items"].get(name))


def list_secret_names() -> list[str]:
    with _lock:
        return sorted(_load()["items"].keys())


def mask(value: str | None) -> str:
    if not value:
        return ""
    v = str(value)
    if len(v) <= 8:
        return "*" * len(v)
    return f"{v[:4]}...{v[-4:]}"


def reset_cache() -> None:
    """Drop the in-memory cache (used by tests)."""
    global _cache
    with _lock:
        _cache = None


def migrate_from_config(cfg) -> list[str]:
    """Move plaintext provider keys from ``config.yaml`` into the store.

    Returns the list of secret names that were created.
    """
    created: list[str] = []
    operation = (cfg or {}).get("operation") or {}
    provider = str(operation.get("provider") or "openai").strip().lower()
    legacy = operation.get("api_key")
    ref = f"provider:{provider}"
    if is_real_secret(legacy) and not has_secret(ref):
        set_secret(ref, str(legacy))
        created.append(ref)
    if is_real_secret(legacy):
        # Never keep the plaintext in config.yaml.
        operation["api_key"] = ""
        cfg["operation"] = operation
    return created

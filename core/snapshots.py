"""File snapshots so every destructive tool call can be undone.

Layout::

    data/snapshots/<id>/manifest.json
    data/snapshots/<id>/files/0000_config.yaml
    data/snapshots/<id>/files/0001_main.py
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import uuid
from pathlib import Path

from . import logs

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / "data" / "snapshots"


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 128), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(snapshot_id: str) -> dict | None:
    path = SNAPSHOT_DIR / snapshot_id / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def create(paths, label: str = "") -> dict:
    """Snapshot the given files (existing ones only) and return the manifest."""
    wanted = [Path(p) for p in (paths or [])]
    existing = []
    for path in wanted:
        try:
            if path.is_file():
                existing.append(path.resolve())
        except Exception:
            continue
    if not existing:
        return {"id": "", "files": [], "label": label, "created_at": _now()}

    snapshot_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    folder = SNAPSHOT_DIR / snapshot_id
    files_dir = folder / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    root = str(ROOT.resolve()).lower()
    entries = []
    for index, path in enumerate(existing):
        target = files_dir / f"{index:04d}_{path.name}"
        try:
            shutil.copy2(path, target)
        except Exception as exc:
            logs.warn(f"Snapshot copy failed for {path}: {exc}")
            continue
        resolved = str(path)
        external = not resolved.lower().startswith(root)
        entries.append({
            "index": index,
            "path": resolved,
            "relative": None if external else str(path.relative_to(ROOT.resolve())),
            "external": external,
            "sha256": _sha256(path),
            "size": path.stat().st_size,
            "stored": target.name,
        })

    manifest = {
        "id": snapshot_id,
        "label": label or "automatic",
        "created_at": _now(),
        "files": entries,
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    prune()
    logs.info(f"Snapshot {snapshot_id} created ({len(entries)} file(s))")
    return manifest


def list_snapshots(limit: int = 100) -> list[dict]:
    if not SNAPSHOT_DIR.exists():
        return []
    items = []
    for folder in SNAPSHOT_DIR.iterdir():
        if not folder.is_dir():
            continue
        manifest = _manifest(folder.name)
        if manifest:
            manifest["total_bytes"] = sum(f.get("size", 0) for f in manifest.get("files", []))
            items.append(manifest)
    items.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return items[:limit]


def get(snapshot_id: str) -> dict | None:
    return _manifest(snapshot_id)


def diff(snapshot_id: str) -> dict:
    manifest = _manifest(snapshot_id)
    if not manifest:
        return {"error": "snapshot não encontrado"}
    changes = []
    for entry in manifest.get("files", []):
        path = Path(entry["path"])
        if not path.exists():
            changes.append({"path": entry["path"], "state": "missing"})
            continue
        current = _sha256(path)
        changes.append({
            "path": entry["path"],
            "state": "modified" if current != entry["sha256"] else "unchanged",
        })
    return {"id": snapshot_id, "changes": changes}


def restore(snapshot_id: str, allow_external: bool = False) -> dict:
    manifest = _manifest(snapshot_id)
    if not manifest:
        return {"restored": 0, "skipped": 0, "error": "snapshot não encontrado"}

    folder = SNAPSHOT_DIR / snapshot_id / "files"
    restored = 0
    skipped = 0
    errors = []

    for entry in manifest.get("files", []):
        if entry.get("external") and not allow_external:
            skipped += 1
            errors.append(f"{entry['path']}: fora do HD (allow_host_write=false)")
            continue
        source = folder / entry["stored"]
        if not source.exists():
            skipped += 1
            errors.append(f"{entry['path']}: cópia ausente")
            continue
        destination = Path(entry["path"])
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            restored += 1
        except Exception as exc:
            skipped += 1
            errors.append(f"{entry['path']}: {exc}")

    logs.info(f"Snapshot {snapshot_id} restored ({restored} file(s), {skipped} skipped)")
    return {"restored": restored, "skipped": skipped, "errors": errors[:20]}


def delete(snapshot_id: str) -> bool:
    folder = SNAPSHOT_DIR / snapshot_id
    if not folder.is_dir():
        return False
    try:
        shutil.rmtree(folder)
        return True
    except Exception as exc:
        logs.warn(f"Could not delete snapshot {snapshot_id}: {exc}")
        return False


def prune(max_keep: int | None = None) -> int:
    if max_keep is None:
        try:
            import yaml
            cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8")) or {}
            max_keep = int((cfg.get("snapshots") or {}).get("max", 20))
        except Exception:
            max_keep = 20
    max_keep = max(1, int(max_keep))
    if not SNAPSHOT_DIR.exists():
        return 0
    folders = sorted(
        [f for f in SNAPSHOT_DIR.iterdir() if f.is_dir()],
        key=lambda f: f.name,
        reverse=True,
    )
    removed = 0
    for folder in folders[max_keep:]:
        try:
            shutil.rmtree(folder)
            removed += 1
        except Exception:
            pass
    return removed


def total_size() -> int:
    if not SNAPSHOT_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in SNAPSHOT_DIR.rglob("*") if f.is_file())

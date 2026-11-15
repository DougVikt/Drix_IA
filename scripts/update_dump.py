#!/usr/bin/env python3
"""Dump the project source files into a JSON snapshot.

Usage::

    .venv/Scripts/python.exe scripts/update_dump.py [reason]

Writes to ``F:/DADOS_DEV/drix_complete_dump.json``.  The output file itself is
never included, so the dump can be regenerated safely in place.
"""
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "DADOS_DEV" / "drix_complete_dump.json"

SKIP_DIRS = {
    ".venv", ".git", "__pycache__", ".cache", ".chainlit",
    "backups", "ia_system", "node_modules", "poetry_cache",
    # Nunca incluir dados persistentes (cofre, bancos, memórias, snapshots).
    "data", "logs", "workspace",
    # Pastas que não fazem parte do código da Drix.
    "$RECYCLE.BIN", "System Volume Information",
    "project-nomad-main", "omniget-main",
}
EXTS = {
    ".py", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".cfg",
    ".html", ".css", ".js", ".bat",
}
SPECIAL_NAMES = {"Makefile", "start.bat"}


def _skipped(path: Path) -> bool:
    """True when the path lives inside a skipped directory."""
    try:
        parts = path.relative_to(ROOT).parts
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in parts)


def main() -> int:
    out_resolved = OUT.resolve()
    files = []
    total_bytes = 0

    for path in ROOT.rglob("*"):
        if path.is_dir():
            continue
        if _skipped(path):
            continue
        try:
            if path.resolve() == out_resolved:
                continue
        except OSError:
            continue
        if path.suffix.lower() not in EXTS and path.name not in SPECIAL_NAMES:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        size = len(content.encode("utf-8"))
        total_bytes += size
        files.append({
            "path": path.relative_to(ROOT).as_posix(),
            "content": content,
            "size": size,
        })

    files.sort(key=lambda item: item["path"])
    payload = {
        "source": "drix",
        "reason": sys.argv[1] if len(sys.argv) > 1 else "manual",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "root": str(ROOT),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Dump updated: {OUT} ({len(files)} files, {total_bytes / 1024 / 1024:.1f} MB of text)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

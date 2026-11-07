#!/usr/bin/env python3
"""Dump the project source files into a JSON snapshot.

Usage::

    .venv/Scripts/python.exe scripts/update_dump.py [reason]

Writes to ``F:/DADOS_DEV/drix_complete_dump.json``.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "DADOS_DEV" / "drix_complete_dump.json"
SKIP_DIRS = {".venv", ".git", "__pycache__", ".cache", "ia_system", ".chainlit", "poetry_cache", "node_modules"}
EXTS = {".py", ".yaml", ".yml", ".toml", ".json", ".md", ".txt", ".cfg", "Makefile"}

files = []
for p in ROOT.rglob("*"):
    if p.is_dir():
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        continue
    if p.suffix.lower() in EXTS or p.name == "Makefile":
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            files.append({"path": str(p.relative_to(ROOT).as_posix()), "content": content, "size": len(content)})
        except Exception:
            pass

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps({"source": "drix", "reason": sys.argv[1] if len(sys.argv) > 1 else "manual", "files": files}, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Dump updated: {OUT} ({len(files)} files)")

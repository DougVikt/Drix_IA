import os
import hashlib
from pathlib import Path

CACHE_ROOT = Path(__file__).resolve().parent.parent / ".cache"


def init_cache():
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _hash_name(name):
    return hashlib.sha256(name.encode()).hexdigest()[:16]


def conversation_dir(name):
    folder = CACHE_ROOT / _hash_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_file(file_bytes, filename, conversation_name):
    conv_dir = conversation_dir(conversation_name)
    dest = conv_dir / filename
    stem = dest.stem
    ext = dest.suffix
    counter = 1
    while dest.exists():
        dest = conv_dir / f"{stem}_{counter}{ext}"
        counter += 1
    with open(dest, "wb") as f:
        f.write(file_bytes)
    return dest.name, str(dest)


def list_files(conversation_name):
    conv_dir = conversation_dir(conversation_name)
    files = []
    for f in sorted(conv_dir.iterdir()):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "path": str(f.relative_to(CACHE_ROOT)),
            })
    return files


def delete_file(filename, conversation_name):
    conv_dir = conversation_dir(conversation_name)
    target = conv_dir / filename
    if target.exists() and target.is_file():
        target.unlink()
        return True
    return False

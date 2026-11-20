"""Python runtime paths for Drix on Windows and Linux.

The distributed Windows copy uses the bundled interpreter at
``ia_system/python/python-3.10.11.amd64``.  The tested third-party packages
live in ``.venv`` and are exposed through a relative ``sitecustomize.py``
inside the portable Python, so no absolute drive letter is stored anywhere.

On Linux (and on a development checkout) the project uses ``.venv/bin/python``
or the interpreter that started the process.

Use :func:`python_exe` / :func:`pythonw_exe` when starting child processes and
:func:`child_env` to build their environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"

PORTABLE_DIR = ROOT / "ia_system" / "python" / "python-3.10.11.amd64"
PORTABLE_PYTHON = PORTABLE_DIR / ("python.exe" if IS_WINDOWS else "bin/python3")
PORTABLE_PYTHONW = PORTABLE_DIR / ("pythonw.exe" if IS_WINDOWS else "bin/python3")

VENV_DIR = ROOT / ".venv"


def _venv_python() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _venv_site() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Lib" / "site-packages"
    # Debian/Ubuntu use lib/, Fedora and some other distros use lib64/.
    for libname in ("lib", "lib64"):
        lib = VENV_DIR / libname
        try:
            candidates = sorted(lib.glob("python*/site-packages"))
        except Exception:
            candidates = []
        if candidates:
            return candidates[0]
    return VENV_DIR / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"


VENV_PYTHON = _venv_python()
VENV_SITE = _venv_site()


def has_portable_python() -> bool:
    """True when the bundled interpreter is present."""
    return PORTABLE_PYTHON.is_file()


def python_exe() -> str:
    """Interpreter used for child Python processes."""
    for candidate in (PORTABLE_PYTHON, VENV_PYTHON):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def pythonw_exe() -> str:
    """Windowless interpreter on Windows, the normal one elsewhere."""
    if IS_WINDOWS:
        if PORTABLE_PYTHONW.is_file():
            return str(PORTABLE_PYTHONW)
        venv_pythonw = VENV_DIR / "Scripts" / "pythonw.exe"
        if venv_pythonw.is_file():
            return str(venv_pythonw)
    return python_exe()


def child_env(extra: dict | None = None) -> dict:
    """Environment for Drix child processes.

    Paths are derived from the project root at runtime, never hard-coded.
    ``PYTHONPATH`` is a safety net in case the portable ``sitecustomize.py``
    is missing; it also makes the tested packages win over older ones.
    """
    env = os.environ.copy()
    env.setdefault("OLLAMA_MODELS", str(ROOT / "ia_system" / "models"))

    path_parts = []
    if IS_WINDOWS:
        path_parts.extend([
            str(PORTABLE_DIR),
            str(VENV_DIR / "Scripts"),
        ])
    else:
        path_parts.append(str(VENV_DIR / "bin"))
    path_parts.extend([
        str(ROOT / "ia_system" / "engine"),
        str(ROOT / "ia_system" / "bin"),
    ])
    env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])

    if VENV_SITE.is_dir():
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(VENV_SITE) + (os.pathsep + current if current else "")

    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env

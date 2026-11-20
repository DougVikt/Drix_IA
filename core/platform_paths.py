"""Cross-platform helpers for paths and bundled binaries.

Drix was originally distributed as a portable folder on Windows.  The same
tree can also run from a normal checkout on Linux, so this module keeps the
few platform differences in one place:

* environment variable expansion accepts both ``%VAR%`` (Windows) and
  ``$VAR`` / ``${VAR}`` (Linux/macOS);
* bundled binaries are looked up with the right extension and fall back to
  the system ``PATH``;
* child processes get the right hidden-window flags only on Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WINDOWS = os.name == "nt"

_WINDOWS_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")

# Windows variables that appear in config.yaml keep working on Linux.
_POSIX_ALIASES = {
    "USERPROFILE": lambda: os.environ.get("HOME", ""),
    "HOMEDRIVE": lambda: "",
    "HOMEPATH": lambda: os.environ.get("HOME", ""),
    "APPDATA": lambda: os.environ.get("XDG_CONFIG_HOME")
    or str(Path.home() / ".config"),
    "LOCALAPPDATA": lambda: os.environ.get("XDG_CACHE_HOME")
    or str(Path.home() / ".cache"),
    "PROGRAMFILES": lambda: "",
    "PROGRAMFILES(X86)": lambda: "",
    "SYSTEMROOT": lambda: "",
    "WINDIR": lambda: "",
    "TEMP": lambda: os.environ.get("TMPDIR") or "/tmp",
    "TMP": lambda: os.environ.get("TMPDIR") or "/tmp",
}


def _expand_windows_vars(text: str) -> str:
    if IS_WINDOWS:
        return os.path.expandvars(text)

    def repl(match: re.Match) -> str:
        name = match.group(1)
        if name in os.environ:
            return os.environ[name]
        getter = _POSIX_ALIASES.get(name.upper())
        return getter() if getter else ""

    return _WINDOWS_VAR.sub(repl, text)


def expand_path(value, base=None) -> Path:
    """Expand ``~``, ``$VAR``, ``${VAR}`` and ``%VAR%`` into a path.

    Relative values are resolved against ``base`` (project root by default).
    """
    text = str(value or "").strip()
    if not text:
        return Path(base or ROOT)
    text = _expand_windows_vars(text)
    text = os.path.expandvars(os.path.expanduser(text))
    path = Path(text)
    if not path.is_absolute():
        path = Path(base or ROOT) / path
    return path


def expand_str(value, base=None) -> str:
    return str(expand_path(value, base=base))


def find_binary(*candidates: str) -> str:
    """Return the first existing file, otherwise the first match in PATH."""
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_file() and (IS_WINDOWS or os.access(path, os.X_OK)):
            return str(path)
    for candidate in candidates:
        if not candidate:
            continue
        found = shutil.which(Path(candidate).name)
        if found:
            return found
    return ""


def ollama_binary() -> str:
    """Bundled Ollama binary, falling back to a system installation."""
    suffix = ".exe" if IS_WINDOWS else ""
    bundled = ROOT / "ia_system" / "engine" / f"ollama{suffix}"
    return find_binary(str(bundled), "ollama")


def pmtiles_binary() -> str:
    """Bundled ``pmtiles`` CLI used by the offline map extractor."""
    suffix = ".exe" if IS_WINDOWS else ""
    bundled = ROOT / "ia_system" / "bin" / f"pmtiles{suffix}"
    return find_binary(str(bundled), "pmtiles")


def ffmpeg_binary() -> str:
    """Bundled or system ffmpeg (imageio-ffmpeg is handled by the caller)."""
    suffix = ".exe" if IS_WINDOWS else ""
    candidates = (
        str(ROOT / "ia_system" / "ffmpeg" / f"ffmpeg{suffix}"),
        str(ROOT / "ia_system" / "bin" / f"ffmpeg{suffix}"),
        "ffmpeg",
    )
    return find_binary(*candidates)


def hidden_process_kwargs() -> dict:
    """``Popen`` kwargs that keep helper processes invisible on Windows."""
    if not IS_WINDOWS:
        return {}
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {
            "startupinfo": startupinfo,
            "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        }
    except Exception:
        return {}


def detach_kwargs() -> dict:
    """``Popen`` kwargs that detach a long-running service from the launcher."""
    if IS_WINDOWS:
        return {}
    return {"start_new_session": True}


def disable_console_close() -> bool:
    """Disable the X button of the current Windows console window.

    The console belongs to the batch launcher and stays open while the
    startup checks run.  Removing ``SC_CLOSE`` from its system menu prevents
    an accidental click from killing the initialization halfway through.
    On Linux (and when there is no console) this is a no-op.
    """
    if not IS_WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        kernel32.GetConsoleWindow.restype = wintypes.HWND
        hwnd = kernel32.GetConsoleWindow()
        if not hwnd:
            return False

        user32.GetSystemMenu.restype = ctypes.c_void_p
        user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.DeleteMenu.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.UINT]
        user32.DeleteMenu.restype = wintypes.BOOL

        menu = user32.GetSystemMenu(hwnd, False)
        if not menu:
            return False

        # SC_CLOSE = 0xF060, MF_BYCOMMAND = 0x00000000
        removed = bool(user32.DeleteMenu(menu, 0xF060, 0x00000000))
        user32.DrawMenuBar(hwnd)
        return removed
    except Exception:
        return False

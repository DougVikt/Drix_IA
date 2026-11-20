"""Create a desktop shortcut for Drix using the official logo.

Windows: creates ``Drix.lnk`` that runs ``pythonw.exe scripts/launcher.py``
(no console window, so there is no terminal X) with
``ia_system/icon/drix.ico`` as the icon.  ``start.bat`` remains available for
diagnostics and for the terminal/headless menu.

Linux: creates ``drix.desktop`` pointing to ``start.sh`` with the PNG logo.

Run it again on another PC after moving the project: the shortcut always uses
the project path resolved from this file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import python_runtime

ICON_PNG = ROOT / "ia_system" / "icon" / "logo_drix2.png"
ICON_ICO = ROOT / "ia_system" / "icon" / "drix.ico"
CONSOLE_LAUNCHER = ROOT / ("start.bat" if os.name == "nt" else "start.sh")
GUI_LAUNCHER = ROOT / "scripts" / "launcher.py"


def make_ico() -> bool:
    """Generate a multi-size .ico from the PNG logo."""
    try:
        if ICON_ICO.exists() and ICON_ICO.stat().st_mtime >= ICON_PNG.stat().st_mtime:
            return True
    except Exception:
        pass
    try:
        from PIL import Image
    except Exception as exc:
        print(f"aviso: Pillow indisponivel para gerar o .ico: {exc}", file=sys.stderr)
        return False
    try:
        image = Image.open(ICON_PNG).convert("RGBA")
        box = image.getbbox()
        if box:
            image = image.crop(box)
        side = max(image.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2), image)
        canvas.save(
            ICON_ICO,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                   (64, 64), (128, 128), (256, 256)],
        )
        return True
    except Exception as exc:
        print(f"aviso: nao foi possivel gerar {ICON_ICO.name}: {exc}", file=sys.stderr)
        return False


def desktop_dir() -> Path:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_DESKTOPDIRECTORY = 0x0010 (handles OneDrive redirection)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buffer) == 0:
                return Path(buffer.value)
        except Exception:
            pass
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    return Path.home() / "Desktop"


def create_windows_shortcut(dest: Path) -> bool:
    icon = ICON_ICO if ICON_ICO.exists() else ICON_PNG
    target = python_runtime.pythonw_exe()
    arguments = f'"{GUI_LAUNCHER}"'
    try:
        import win32com.client

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(dest))
        shortcut.TargetPath = target
        shortcut.Arguments = arguments
        shortcut.WorkingDirectory = str(ROOT)
        shortcut.IconLocation = f"{icon},0"
        shortcut.Description = "Drix - IA portatil"
        shortcut.Save()
        return True
    except Exception as exc:
        print(f"aviso: win32com falhou ({exc}); tentando PowerShell...", file=sys.stderr)

    def quote(value: str) -> str:
        return value.replace("'", "''")

    command = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{dest}');"
        "$s.TargetPath='{target}';$s.Arguments='{args}';$s.WorkingDirectory='{cwd}';"
        "$s.IconLocation='{icon}';$s.Description='Drix - IA portatil';$s.Save()"
    ).format(
        dest=quote(str(dest)),
        target=quote(target),
        args=quote(arguments),
        cwd=quote(str(ROOT)),
        icon=quote(f"{icon},0"),
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", command],
            check=True,
        )
        return True
    except Exception as exc:
        print(f"erro: nao foi possivel criar o atalho: {exc}", file=sys.stderr)
        return False


def create_linux_shortcut(dest: Path) -> bool:
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Drix\n"
        "Comment=Drix - IA portatil\n"
        f'Exec="{CONSOLE_LAUNCHER}"\n'
        f"Path={ROOT}\n"
        f"Icon={ICON_PNG}\n"
        "Terminal=true\n"
        "Categories=Utility;\n"
    )
    try:
        dest.write_text(content, encoding="utf-8")
        dest.chmod(0o755)
        return True
    except Exception as exc:
        print(f"erro: nao foi possivel criar o atalho: {exc}", file=sys.stderr)
        return False


def main() -> int:
    if not GUI_LAUNCHER.exists():
        print(f"erro: launcher nao encontrado: {GUI_LAUNCHER}", file=sys.stderr)
        return 1
    if not CONSOLE_LAUNCHER.exists():
        print(f"erro: launcher de console nao encontrado: {CONSOLE_LAUNCHER}", file=sys.stderr)
        return 1
    make_ico()
    desktop = desktop_dir()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"erro: area de trabalho indisponivel: {exc}", file=sys.stderr)
        return 1
    dest = desktop / ("Drix.lnk" if os.name == "nt" else "drix.desktop")
    ok = create_windows_shortcut(dest) if os.name == "nt" else create_linux_shortcut(dest)
    if ok:
        print(f"Atalho criado: {dest}")
        print(f"Icone: {ICON_ICO if ICON_ICO.exists() else ICON_PNG}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

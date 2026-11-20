"""Graphical Drix launcher with the official logo.

The desktop shortcut points here instead of ``start.bat`` so normal use does
not open a console window (and therefore has no terminal X to close).  The
checker runs hidden with ``--mode ... --quiet`` and the service opens the web
UI as usual.  ``start.bat`` remains available for diagnostics and for the
terminal/headless menu.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import python_runtime

BG = "#0e0e1a"
CARD = "#151525"
TEXT = "#e0e0e0"
MUTED = "#8a8aa3"
GREEN = "#3ddc84"
RED = "#ff5c5c"
AMBER = "#ffb020"
ACCENT = "#4f8cff"

CHECKER = ROOT / "core" / "checker.py"
LOGO_PNG = ROOT / "ia_system" / "icon" / "logo_drix2.png"
LOGO_ICO = ROOT / "ia_system" / "icon" / "drix.ico"
LOG_PATH = ROOT / "logs" / "launcher.log"


class Launcher(tk.Tk):
    def __init__(self):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Drix.PortableAI")
            except Exception:
                pass
        super().__init__()
        self.title("Drix")
        self.configure(bg=BG)
        self.geometry("420x360")
        self.resizable(False, False)
        self._proc: subprocess.Popen | None = None
        self._logo = None
        self._apply_icon()
        self._build()

    def _apply_icon(self):
        if LOGO_ICO.exists():
            try:
                self.iconbitmap(str(LOGO_ICO))
            except Exception:
                pass
        try:
            from PIL import Image, ImageTk
            image = Image.open(LOGO_PNG).convert("RGBA")
            image.thumbnail((96, 96), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(image)
            self.iconphoto(True, self._logo)
        except Exception:
            pass

    def _build(self):
        if self._logo is not None:
            tk.Label(self, image=self._logo, bg=BG).pack(pady=(24, 8))
        else:
            tk.Label(self, text="D", bg=BG, fg=ACCENT,
                     font=("Segoe UI", 30, "bold")).pack(pady=(24, 8))
        tk.Label(self, text="Drix", bg=BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack()
        tk.Label(self, text="IA portátil", bg=BG, fg=MUTED,
                 font=("Segoe UI", 10)).pack(pady=(0, 18))

        card = tk.Frame(self, bg=CARD)
        card.pack(fill="x", padx=28)

        self.web_btn = self._button(card, "Abrir interface web", ACCENT,
                                    lambda: self._start("web"))
        self.web_btn.pack(fill="x", padx=10, pady=(12, 5))
        self.headless_btn = self._button(card, "Servidor sem navegador", "#252540",
                                         lambda: self._start("headless"))
        self.headless_btn.pack(fill="x", padx=10, pady=(0, 12))

        self.status = tk.Label(self, text="Pronto para iniciar", bg=BG, fg=MUTED,
                               font=("Segoe UI", 10))
        self.status.pack(pady=(16, 2))
        self.log_btn = tk.Button(
            self, text="Abrir log", command=self._open_log,
            bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT,
            relief="flat", bd=0, highlightthickness=0, cursor="hand2",
            font=("Segoe UI", 9, "underline"),
        )

    def _button(self, parent, text, color, command):
        return tk.Button(
            parent, text=text, command=command, bg=color, fg=TEXT,
            activebackground="#1f1f38", activeforeground=TEXT,
            relief="flat", bd=0, highlightthickness=0,
            font=("Segoe UI", 10), padx=10, pady=8, cursor="hand2",
        )

    def _start(self, mode: str):
        if self._proc is not None and self._proc.poll() is None:
            return
        self.web_btn.configure(state="disabled")
        self.headless_btn.configure(state="disabled")
        self.log_btn.pack_forget()
        self.status.configure(
            text="Iniciando..." if mode == "web" else "Iniciando servidor...",
            fg=AMBER,
        )

        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        env = python_runtime.child_env()
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = 0
                kwargs["startupinfo"] = startup
            except Exception:
                pass

        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        try:
            self._proc = subprocess.Popen(
                [python_runtime.python_exe(), str(CHECKER), "--mode", mode, "--quiet"],
                cwd=str(ROOT),
                env=env,
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                **kwargs,
            )
        except Exception as exc:
            log.close()
            self._failed(f"Falha ao iniciar: {exc}")
            return
        log.close()  # the child keeps its own handle
        self.after(300, self._poll)

    def _poll(self):
        if self._proc is None:
            return
        code = self._proc.poll()
        if code is None:
            self.after(300, self._poll)
            return
        if code == 0:
            self.status.configure(text="Drix iniciada", fg=GREEN)
            self.after(1300, self.destroy)
        else:
            self._failed(f"Falha ao iniciar (código {code})")

    def _failed(self, message: str):
        self.status.configure(text=message, fg=RED)
        self.web_btn.configure(state="normal")
        self.headless_btn.configure(state="normal")
        self.log_btn.pack(pady=(2, 0))

    def _open_log(self):
        paths = [LOG_PATH, ROOT / "logs" / "drix.log"]
        target = next((path for path in paths if path.exists()), LOG_PATH)
        try:
            if os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception:
            pass


def main() -> int:
    Launcher().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

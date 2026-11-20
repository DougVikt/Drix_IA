"""Drix desktop indicator.

A small always-on-top window that shows whether the Ollama engine and the web
server are still alive after the browser is closed.  It also lets the user stop
everything from one place.

Run directly::

    .venv\\Scripts\\python.exe scripts\\indicator.py

It writes its own pid into ``data/runtime.json`` so the web UI can report it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import logs, runtime
from core import python_runtime


def _ensure_pythonw() -> None:
    """Reinicia com pythonw.exe se estiver rodando com python.exe (evita console)."""
    if sys.platform != "win32":
        return
    if not sys.executable.lower().endswith("python.exe"):
        return
    pythonw = python_runtime.pythonw_exe()
    if not pythonw:
        return
    try:
        if Path(pythonw).resolve() == Path(sys.executable).resolve():
            return
    except Exception:
        pass

    log_path = ROOT / "logs" / "indicator_stderr.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        log = open(log_path, "a", encoding="utf-8", buffering=1)
        subprocess.Popen(
            [pythonw, str(__file__)] + sys.argv[1:],
            cwd=str(ROOT),
            env=python_runtime.child_env(),
            creationflags=0x08000000,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
        )
        log.close()  # the child keeps its own handle
    except Exception as exc:
        try:
            with open(ROOT / "logs" / "indicator_error.log", "a", encoding="utf-8") as fh:
                fh.write(f"Falha ao relancar com pythonw: {exc}\n")
        except Exception:
            pass
        return
    sys.exit(0)



BG = "#0e0e1a"
CARD = "#151525"
TEXT = "#e0e0e0"
MUTED = "#8a8aa3"
GREEN = "#3ddc84"
RED = "#ff5c5c"
AMBER = "#ffb020"
ACCENT = "#4f8cff"


class Indicator(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drix — serviços")
        self.configure(bg=BG)
        self.geometry("+%d+%d" % self._corner_position())
        self.minsize(300, 230)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)
        self.after(50, self._disable_close_button)

        self._logo_icon = self._logo_photo(64)
        if self._logo_icon is not None:
            try:
                self.iconphoto(True, self._logo_icon)
            except Exception:
                pass
        ico = ROOT / "ia_system" / "icon" / "drix.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass

        self.ui_font = self._pick_font()
        self._snapshot: dict = {}
        self._busy = False
        self._stopping = False
        self._stop_finished = False

        self._build()
        runtime.register("indicator", pid=__import__("os").getpid())
        self.after(100, self.refresh)
        self.after(2200, self._tick)

    def _corner_position(self):
        try:
            self.update_idletasks()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            return sw - 340, sh - 300
        except Exception:
            return 40, 40

    def _pick_font(self) -> str:
        """Use a font that exists on the current platform (Tk falls back)."""
        try:
            import tkinter.font as tkfont
            return tkfont.nametofont("TkDefaultFont").actual("family") or "Segoe UI"
        except Exception:
            return "Segoe UI"

    # ─── UI ──────────────────────────────────────────────────

    def _logo_photo(self, size: int):
        """Carrega a logo oficial em um tamanho adequado ao Tk."""
        path = ROOT / "ia_system" / "icon" / "logo_drix2.png"
        if not path.exists():
            return None
        try:
            from PIL import Image, ImageTk
            image = Image.open(path).convert("RGBA")
            image.thumbnail((size, size), Image.LANCZOS)
            return ImageTk.PhotoImage(image)
        except Exception:
            return None

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 2))

        self._logo_header = self._logo_photo(26)
        if self._logo_header is not None:
            tk.Label(header, image=self._logo_header, bg=BG).pack(side="left", padx=(0, 7))

        tk.Label(header, text="Drix", bg=BG, fg=TEXT,
                 font=(self.ui_font, 13, "bold")).pack(side="left")
        self.overall = tk.Label(header, text="verificando…", bg=BG, fg=MUTED,
                                font=(self.ui_font, 9))
        self.overall.pack(side="right")

        card = tk.Frame(self, bg=CARD)
        card.pack(fill="x", padx=12, pady=8)

        self.rows = {}
        for key, label in (("engine", "Motor (Ollama)"), ("web", "Web"), ("indicator", "Indicador")):
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", padx=10, pady=5)
            dot = tk.Label(row, text="●", bg=CARD, fg=MUTED, font=(self.ui_font, 12))
            dot.pack(side="left")
            name = tk.Label(row, text=label, bg=CARD, fg=TEXT,
                            font=(self.ui_font, 10), anchor="w")
            name.pack(side="left", padx=(6, 0))
            detail = tk.Label(row, text="", bg=CARD, fg=MUTED,
                              font=(self.ui_font, 9))
            detail.pack(side="right")
            self.rows[key] = (dot, detail)

        buttons = tk.Frame(self, bg=BG)
        buttons.pack(fill="x", padx=12, pady=(4, 12))

        self._button(buttons, "Abrir Web", self._open_web, ACCENT, 0)
        self._button(buttons, "Reiniciar motor", self._restart_engine, CARD, 1)
        self._button(buttons, "Parar tudo", self._stop_all, "#44202a", 2)

    def _button(self, parent, text, command, color, column):
        btn = tk.Button(
            parent, text=text, command=command, bg=color, fg=TEXT,
            activebackground="#1f1f38", activeforeground=TEXT,
            relief="flat", bd=0, highlightthickness=0,
            font=(self.ui_font, 9), padx=8, pady=6, cursor="hand2",
        )
        btn.grid(row=column // 2, column=column % 2, sticky="ew", padx=3, pady=3)
        parent.grid_columnconfigure(column % 2, weight=1)
        return btn

    # ─── Status ──────────────────────────────────────────────

    def _tick(self):
        self.refresh()
        self.after(2200, self._tick)

    def refresh(self):
        if self._busy:
            return
        self._busy = True

        def _work():
            try:
                snap = runtime.status()
            except Exception as exc:  # pragma: no cover
                snap = {"error": str(exc)}
            try:
                self.after(0, lambda: self._apply(snap))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _apply(self, snap: dict):
        self._busy = False
        self._snapshot = snap

        # Enquanto o "Parar tudo" está em andamento, o painel manda na tela.
        if self._stopping:
            if not self._stop_finished:
                self.overall.configure(text="parando...", fg=AMBER)
                for dot, detail in self.rows.values():
                    dot.configure(fg=AMBER)
            return

        if snap.get("error"):
            self.overall.configure(text="erro", fg=RED)
            return

        engine = snap.get("engine") or {}
        web = snap.get("web") or {}
        indicator = snap.get("indicator") or {}

        self._set_row("engine", bool(engine.get("running")),
                      f"porta {engine.get('port', '—')}")
        self._set_row("web", bool(web.get("port_open")),
                      f"{web.get('host', '—')}:{web.get('port', '—')}")
        self._set_row("indicator", bool(indicator.get("pid_alive")), "")

        if engine.get("running"):
            self.overall.configure(text="ativos", fg=GREEN)
        elif web.get("port_open"):
            self.overall.configure(text="web sem motor", fg=AMBER)
        else:
            self.overall.configure(text="parado", fg=MUTED)

    def _set_row(self, key, alive: bool, detail: str):
        dot, detail_label = self.rows[key]
        dot.configure(fg=GREEN if alive else RED)
        detail_label.configure(text=detail)

    # ─── Actions ─────────────────────────────────────────────

    def _on_close_requested(self):
        # Evita fechar o painel sem parar os serviços.
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "Drix",
                "Use 'Parar tudo' para encerrar os serviços com segurança.\n"
                "O painel de serviços não pode ser fechado pelo X.",
                parent=self,
            )
        except Exception:
            pass

    def _disable_close_button(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            if not hwnd:
                hwnd = self.winfo_id()
            GWL_STYLE = -16
            WS_SYSMENU = 0x00080000
            WS_MINIMIZEBOX = 0x00020000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            # Keep a minimal frame; remove/disable close behavior at protocol level too.
            style = (style & ~WS_SYSMENU) | WS_MINIMIZEBOX
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, style)
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)  # refresh frame
        except Exception:
            # Fallback: protocol handler already prevents closing.
            pass

    def _open_web(self):
        web = self._snapshot.get("web") or {}
        host = web.get("host", "127.0.0.1")
        port = web.get("port", 8000)
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    def _restart_engine(self):
        def _work():
            runtime.stop_engine()
            runtime.start_engine()
            self.after(0, self.refresh)

        threading.Thread(target=_work, daemon=True).start()

    def _stop_all(self):
        if self._stopping:
            return
        if not self._confirm("Parar motor, web e indicador?"):
            return

        # 1) Indicar ação no painel imediatamente
        self._stopping = True
        self.overall.configure(text="parando...", fg=AMBER)
        for dot, detail in self.rows.values():
            dot.configure(fg=AMBER)

        def _work():
            front = ROOT / "ui" / "front"
            index_path = front / "index.html"
            stopped_path = front / "stopped.html"
            backup = front / "index.html.bak"

            # 2) Troca a página inicial pela página de parada e avisa o navegador
            try:
                if not backup.exists() and index_path.exists():
                    shutil.copyfile(index_path, backup)
                if stopped_path.exists():
                    shutil.copyfile(stopped_path, index_path)
                runtime.begin_stop()
            except Exception as exc:
                logs.info(f"Stop prepare error: {exc}")

            # 3) Espera a aba consultar /api/runtime e trocar de tela
            time.sleep(2.5)

            # 4) Para o servidor web (mata o watchdog) e depois o motor
            try:
                runtime.stop_web()
            except Exception as exc:
                logs.info(f"Stop web error: {exc}")
            try:
                runtime.stop_engine()
            except Exception as exc:
                logs.info(f"Stop engine error: {exc}")

            # 5) Verifica que nada está ativo
            all_down = False
            for _ in range(20):
                s = runtime.status()
                engine_ok = bool(s.get("engine") and s["engine"].get("running"))
                web_ok = bool(s.get("web") and s["web"].get("port_open"))
                if not engine_ok and not web_ok:
                    all_down = True
                    break
                time.sleep(0.5)

            if not all_down:
                # Não fecha a janela: ainda há serviço ativo.
                logs.warn("Stop verification failed: engine or web still active")
                self._stopping = False
                self.after(0, lambda: self.overall.configure(text="falha ao parar", fg=RED))
                return

            # 6) Mostrar "parado" no painel
            self._stop_finished = True
            self.after(0, lambda: self.overall.configure(text="parado", fg=RED))
            for dot, detail in self.rows.values():
                self.after(0, lambda d=dot: d.configure(fg=RED))

            # 7) Fechar a janela de monitoramento só depois de confirmar
            self.after(1400, lambda: self.destroy())

        threading.Thread(target=_work, daemon=True).start()

    def _confirm(self, message: str) -> bool:
        from tkinter import messagebox

        return messagebox.askyesno("Drix", message, parent=self)


def main() -> int:
    _ensure_pythonw()
    app = Indicator()
    app.mainloop()
    try:
        runtime.unregister("indicator")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

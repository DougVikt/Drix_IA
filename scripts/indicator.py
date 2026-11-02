"""Drix desktop indicator.

A small always-on-top window that shows whether the Ollama engine and the web
server are still alive after the browser is closed.  It also lets the user stop
everything from one place.

Run directly::

    .venv\\Scripts\\python.exe scripts\\indicator.py

It writes its own pid into ``data/runtime.json`` so the web UI can report it.
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import runtime  # noqa: E402

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
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._snapshot: dict = {}
        self._busy = False

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

    # ─── UI ──────────────────────────────────────────────────

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=14, pady=(12, 2))
        tk.Label(header, text="◆ Drix", bg=BG, fg=TEXT,
                 font=("Segoe UI", 13, "bold")).pack(side="left")
        self.overall = tk.Label(header, text="verificando…", bg=BG, fg=MUTED,
                                font=("Segoe UI", 9))
        self.overall.pack(side="right")

        card = tk.Frame(self, bg=CARD)
        card.pack(fill="x", padx=12, pady=8)

        self.rows = {}
        for key, label in (("engine", "Motor (Ollama)"), ("web", "Web"), ("indicator", "Indicador")):
            row = tk.Frame(card, bg=CARD)
            row.pack(fill="x", padx=10, pady=5)
            dot = tk.Label(row, text="●", bg=CARD, fg=MUTED, font=("Segoe UI", 12))
            dot.pack(side="left")
            name = tk.Label(row, text=label, bg=CARD, fg=TEXT,
                            font=("Segoe UI", 10), anchor="w")
            name.pack(side="left", padx=(6, 0))
            detail = tk.Label(row, text="", bg=CARD, fg=MUTED,
                              font=("Segoe UI", 9))
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
            font=("Segoe UI", 9), padx=8, pady=6, cursor="hand2",
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
            self.after(0, lambda: self._apply(snap))

        threading.Thread(target=_work, daemon=True).start()

    def _apply(self, snap: dict):
        self._busy = False
        self._snapshot = snap
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

    def _open_web(self):
        web = self._snapshot.get("web") or {}
        host = web.get("host", "127.0.0.1")
        port = web.get("port", 8000)
        webbrowser.open(f"http://{host}:{port}")

    def _restart_engine(self):
        def _work():
            runtime.stop_engine()
            runtime.start_engine()
            self.after(0, self.refresh)

        threading.Thread(target=_work, daemon=True).start()

    def _stop_all(self):
        if not _confirm("Parar motor, web e indicador?"):
            return

        def _work():
            runtime.stop_all()
            self.after(0, self.destroy)

        threading.Thread(target=_work, daemon=True).start()

    def _confirm(self, message: str) -> bool:
        from tkinter import messagebox

        return messagebox.askyesno("Drix", message, parent=self)


def main() -> int:
    app = Indicator()
    app.mainloop()
    try:
        runtime.unregister("indicator")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

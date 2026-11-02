import customtkinter as ctk
import sys
import asyncio
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.main import ask, atualizar_aprendizado, ConversationManager, config

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

conv_mgr = ConversationManager()
conv_mgr.set_workspace("desktop_default")

COR_USER = "#2b5278"
COR_AI = "#1e1e2e"
COR_FUNDO = "#0e0e1a"
COR_SIDEBAR = "#151525"
COR_TEXTO = "#e0e0e0"


class ChatBubble(ctk.CTkFrame):
    def __init__(self, master, texto, tipo="user", **kwargs):
        bg = COR_USER if tipo == "user" else COR_AI
        super().__init__(master, fg_color=bg, corner_radius=12, **kwargs)
        align = "e" if tipo == "user" else "w"
        self.pack(fill="x", padx=(60 if tipo == "user" else 10, 10 if tipo == "user" else 60), pady=4, anchor=align)
        lbl = ctk.CTkLabel(self, text=texto, wraplength=450, justify="left" if tipo == "ai" else "right",
                           font=("Segoe UI", 13), text_color=COR_TEXTO)
        lbl.pack(padx=14, pady=10)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Drix - IA Portatil")
        self.geometry("900x600")
        self.minsize(700, 450)
        self.configure(fg_color=COR_FUNDO)

        self.grid_columnconfigure(0, weight=0, minsize=220)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self, fg_color=COR_SIDEBAR, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nswe")
        self._criar_sidebar()

        # Chat area
        self.chat_frame = ctk.CTkFrame(self, fg_color=COR_FUNDO, corner_radius=0)
        self.chat_frame.grid(row=0, column=1, sticky="nswe")
        self.chat_frame.grid_rowconfigure(1, weight=1)
        self.chat_frame.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self.chat_frame, fg_color="#12121f", height=50, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        ctk.CTkLabel(header, text="Drix - IA Portatil", font=("Segoe UI", 16, "bold"),
                     text_color=COR_TEXTO).pack(side="left", padx=16, pady=10)

        # Mensagens
        self.msg_container = ctk.CTkScrollableFrame(self.chat_frame, fg_color=COR_FUNDO, corner_radius=0)
        self.msg_container.grid(row=1, column=0, sticky="nswe")
        self.msg_container.grid_columnconfigure(0, weight=1)

        # Input
        input_frame = ctk.CTkFrame(self.chat_frame, fg_color="#12121f", height=60, corner_radius=0)
        input_frame.grid(row=2, column=0, sticky="ew")
        input_frame.grid_propagate(False)
        input_frame.grid_columnconfigure(0, weight=1)

        self.entry = ctk.CTkEntry(input_frame, placeholder_text="Digite sua mensagem...",
                                   font=("Segoe UI", 14), height=36,
                                   fg_color="#1e1e3a", border_color="#2a2a5a")
        self.entry.grid(row=0, column=0, padx=(12, 6), pady=10, sticky="ew")
        self.entry.bind("<Return>", lambda e: self.enviar())

        btn_enviar = ctk.CTkButton(input_frame, text=">", width=48, height=36,
                                    fg_color="#2b5278", hover_color="#3a6a9a",
                                    font=("Segoe UI", 16), command=self.enviar)
        btn_enviar.grid(row=0, column=1, padx=(0, 12), pady=10)

        self.adicionar_msg("Ola! Sou a Drix, sua IA portatil. Como posso ajudar?", "ai")

    def _criar_sidebar(self):
        icon_path = Path(__file__).parent.parent / "ia_system" / "icon"
        if icon_path.is_dir():
            imgs = icon_path.glob("drix_icon.svg")
            if imgs:
                from PIL import Image
                img = ctk.CTkImage(Image.open(imgs[0]), size=(40, 40))
                ctk.CTkLabel(self.sidebar, image=img, text="").pack(pady=(20, 0))
        ctk.CTkLabel(self.sidebar, text="Drix", font=("Segoe UI", 20, "bold"),
                     text_color=COR_TEXTO).pack(pady=(4, 16))
        ctk.CTkLabel(self.sidebar, text=f"Modo: {config.get('operation', 'mode', default='local').upper()}",
                     font=("Segoe UI", 12), text_color="#888").pack(pady=(0, 4))
        ctk.CTkLabel(self.sidebar, text=f"Modelo: {config.get('brain', 'local_model', default='qwen2.5:7b')}",
                     font=("Segoe UI", 11), text_color="#666").pack(pady=(0, 12))
        ctk.CTkButton(self.sidebar, text="Sincronizar Licoes", command=self.sincronizar,
                       fg_color="#2b5278", hover_color="#3a6a9a").pack(padx=14, pady=4, fill="x")
        ctk.CTkButton(self.sidebar, text="Limpar Conversa", command=self.limpar,
                       fg_color="#4a2525", hover_color="#6a3535").pack(padx=14, pady=4, fill="x")
        ctk.CTkButton(self.sidebar, text="Tema Claro/Escuro", command=self.trocar_tema,
                       fg_color="#252540", hover_color="#353560").pack(padx=14, pady=4, fill="x")
        status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_frame.pack(side="bottom", fill="x", padx=14, pady=14)
        modo = config.get("operation", "mode", default="local")
        cor = "#34d399" if modo == "local" else "#60a5fa"
        ctk.CTkLabel(status_frame, text=f"  {modo.upper()}", font=("Segoe UI", 12),
                     text_color=cor).pack()

    def adicionar_msg(self, texto, tipo="user"):
        ChatBubble(self.msg_container, texto, tipo)
        self.after(50, lambda: self.msg_container._parent_canvas.yview_moveto(1.0))

    def enviar(self):
        texto = self.entry.get().strip()
        if not texto:
            return
        self.entry.delete(0, "end")
        if texto.lower() == "/aprender":
            self.adicionar_msg(texto, "user")
            threading.Thread(target=self._sincronizar_thread, daemon=True).start()
            return
        if texto.lower() in ["/limpar", "/clear"]:
            self.limpar()
            return
        self.adicionar_msg(texto, "user")
        self.loading = ChatBubble(self.msg_container, "...", "ai")
        threading.Thread(target=self._responder_thread, args=(texto,), daemon=True).start()

    def _responder_thread(self, texto):
        try:
            resposta = asyncio.run(ask(texto, conv_mgr))
        except Exception as e:
            resposta = f"Error: {e}"
        self.after(0, lambda: self._substituir_loading(resposta))

    def _substituir_loading(self, texto):
        if hasattr(self, "loading") and self.loading:
            self.loading.destroy()
        self.adicionar_msg(texto, "ai")

    def sincronizar(self):
        threading.Thread(target=self._sincronizar_thread, daemon=True).start()

    def _sincronizar_thread(self):
        self.after(0, lambda: self.adicionar_msg("Sincronizando licoes...", "ai"))
        ok = atualizar_aprendizado()
        msg = "Licoes sincronizadas!" if ok else "Nenhuma licao nova."
        self.after(500, lambda: self.adicionar_msg(msg, "ai"))

    def limpar(self):
        for w in self.msg_container.winfo_children():
            w.destroy()

    def trocar_tema(self):
        tema_atual = ctk.get_appearance_mode()
        ctk.set_appearance_mode("light" if tema_atual == "Dark" else "dark")


if __name__ == "__main__":
    app = App()
    app.mainloop()

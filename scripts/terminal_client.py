import sys
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client.drix_client import DrixClient

import os
with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as _f:
    _cfg = yaml.safe_load(_f) or {}
_web = _cfg.get("web", {})
_api_key = os.environ.get("DRIX_SECURITY_API_KEY", "").strip() or str((_cfg.get("security") or {}).get("api_key", "") or "")
# Support {env:VAR} in legacy config values
if _api_key.startswith("{env:") and _api_key.endswith("}"):
    _api_key = os.environ.get(_api_key[5:-1], "")
_base_url = f"http://{_web.get('host', '127.0.0.1')}:{_web.get('port', 8000)}"

drix = DrixClient(base_url=_base_url, api_key=_api_key)
LANG = "en"

_translations = {
    "en": {
        "prompt": "User:", "drix": "Drix:", "welcome": "Drix — Portable AI. Type /help for commands.",
        "goodbye": "Goodbye!", "busy": "Processing...",
        "help": """Commands:
  /help          - Show this help
  /clear         - Clear screen
  /lang <code>   - Change language (en/pt)
  /buscar <q>    - Web search
  /site <url>    - Fetch a webpage
  /sync          - Sync config & models
  /learn         - Force learning update
  /status        - Show system status
  /quit          - Exit""",
    },
    "pt": {
        "prompt": "Você:", "drix": "Drix:", "welcome": "Drix — IA Portátil. Digite /help para comandos.",
        "goodbye": "Até logo!", "busy": "Processando...",
        "help": """Comandos:
  /help          - Mostrar ajuda
  /clear         - Limpar tela
  /lang <code>   - Mudar idioma (en/pt)
  /buscar <q>    - Busca na web
  /site <url>    - Ler página
  /sync          - Sincronizar config
  /learn         - Forçar aprendizado
  /status        - Status do sistema
  /quit          - Sair""",
    },
}

def tr(key):
    return _translations.get(LANG, _translations["en"]).get(key, key)

def main():
    global LANG
    print(f"\n  {'='*60}")
    print(f"  DRIX — Terminal Client")
    print(f"  {'='*60}")
    print(f"  {tr('welcome')}")
    print()

    while True:
        try:
            user_input = input(f"\n{tr('prompt')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{tr('goodbye')}")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd in ("/quit", "/sair", "exit"):
            print(f"{tr('drix')} {tr('goodbye')}")
            break

        if cmd == "/help":
            print(tr("help"))
            continue

        if cmd in ("/clear", "/limpar"):
            print("\033[2J\033[H", end="")
            continue

        if cmd.startswith("/lang "):
            code = cmd[6:].strip()
            if code in _translations:
                global LANG
                LANG = code
                print(f"{tr('drix')} Language: {code}")
            else:
                print(f"{tr('drix')} Invalid code. Use: en, pt")
            continue

        if cmd in ("/learn", "/aprender"):
            print(f"{tr('drix')} {tr('busy')}")
            r = drix.chat("/learn")
            print(f"{tr('drix')} {r.get('text', 'OK')}")
            continue

        if cmd in ("/sync", "/sincronizar"):
            print(f"{tr('drix')} {tr('busy')}")
            r = drix.sync()
            changes = r.get("changes", [])
            if changes:
                for c in changes:
                    print(f"  {c}")
            else:
                print(f"{tr('drix')} No changes.")
            continue

        if cmd.startswith("/buscar ") or cmd.startswith("/search "):
            query = user_input.split(maxsplit=1)[1] if len(user_input.split(maxsplit=1)) > 1 else ""
            if query:
                print(f"{tr('drix')} Searching...")
                r = drix.buscar(query)
                results = r.get("results", [])
                print(f"{tr('drix')}\n" + "\n\n".join(results))
            else:
                print(f"{tr('drix')} Usage: /buscar <query>")
            continue

        if cmd.startswith("/site ") or cmd.startswith("/pagina "):
            url = user_input.split(maxsplit=1)[1] if len(user_input.split(maxsplit=1)) > 1 else ""
            if url:
                print(f"{tr('drix')} Fetching {url}...")
                r = drix.site(url)
                print(f"{tr('drix')}\n" + r.get("content", "")[:3000])
            else:
                print(f"{tr('drix')} Usage: /site <url>")
            continue

        if cmd == "/status":
            r = drix.status()
            hw = r.get("hardware", {})
            print(f"{tr('drix')} Mode: {r.get('mode', '?')} / Engine: {'ON' if r.get('engine_running') else 'OFF'}")
            print(f"  Model: {hw.get('selected_model', '?')} / RAM: {hw.get('ram_gb', '?')}GB / CPU: {hw.get('cpu_cores', '?')} cores")
            continue

        print(f"{tr('drix')} {tr('busy')}")
        r = drix.chat(user_input)
        print(f"{tr('drix')} {r.get('text', 'Error')}")

if __name__ == "__main__":
    main()

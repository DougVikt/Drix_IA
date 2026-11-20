import sys, os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_MODELS", str(ROOT / "ia_system" / "models"))

import core.hardware as hardware
import yaml
from core import python_runtime
from core import platform_paths

platform_paths.disable_console_close()

with open(ROOT / "config" / "config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

hw = hardware.analyze()

if os.name == "nt":
    try:
        print("\033[8;30;60t", end="", flush=True)
    except Exception:
        pass
import core.language as lang
lang.set_language(config.get("language", "en"))

def banner_drix():
    banner = """        
            ██████╗ ██████╗ ██╗██╗  ██╗
            ██╔══██╗██╔══██╗██║╚██╗██╔╝
            ██║  ██║██████╔╝██║ ╚███╔╝ 
            ██║  ██║██╔══██╗██║ ██╔██╗ 
            ██████╔╝██║  ██║██║██╔╝ ██╗
            ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝
    """
    return banner

print(banner_drix())
print("=" * 58)
print("               DRIX - PORTABLE AI SETUP")
print("=" * 58)
print()
print("  Host Hardware:")
print(f"    RAM:      {hw['ram_gb']} GB")
print(f"    CPU:      {hw['cpu_cores']} cores")

gpu_info = hw.get("gpu_info", {})
gpu_found = False
if gpu_info.get("nvidia"):
    g = gpu_info["nvidia"]
    print(f"    GPU:      NVIDIA {g['name']} ({g['vram']})")
    gpu_found = True
elif gpu_info.get("amd"):
    print(f"    GPU:      AMD {gpu_info['amd']['name']}")
    gpu_found = True
elif gpu_info.get("vulkan"):
    print(f"    GPU:      Vulkan ({gpu_info['vulkan']['name']})")
    gpu_found = True
if not gpu_found:
    print("    GPU:      not detected (CPU mode)")

print()
print("  Installed models:")
if hw["installed_models"]:
    for m in hw["installed_models"]:
        marker = " (active)" if m == config.get("brain", {}).get("local_model") else ""
        print(f"    - {m}{marker}")
else:
    print("    (none)")

active_model = config.get("brain", {}).get("local_model") or config.get("operation", {}).get("model") or "not set"
suggested = hw.get("selected_model")
auto_select = config.get("brain", {}).get("auto_select_model", False)
print()
print(f"  Active model:    {active_model}")
if suggested and suggested != active_model:
    print(f"  Suggested model: {suggested} (based on hardware)")
elif suggested and auto_select:
    print(f"  Suggested model: {suggested} (auto-select enabled)")
print("  Tip: change the model in config.yaml or in the UI settings.")
if hw["ram_gb"] < 8:
    print("  (!) Low RAM - expect slower responses")

# Network permissions check (config-driven)
net = config.get("network", {}) or {}
net_allow = bool(net.get("allow_internet_access", False))
net_block_local = bool(net.get("block_local_network", True))
net_domains = net.get("allowed_domains") or []
print()
print("  Network permissions:")
print(f"    Internet access:   {'ENABLED' if net_allow else 'DISABLED'} (network.allow_internet_access)")
print(f"    Block local net:   {'ENABLED' if net_block_local else 'DISABLED'} (network.block_local_network)")
if net_allow:
    scope = "all domains" if not net_domains else f"{len(net_domains)} allowed domain(s)"
    print(f"    Allowed scope:     {scope}")
else:
    print("    Web tools (search/fetch/MCP remote) require internet access to be enabled.")

print()
print("  Choose interface:")
print("    1 - Terminal (CLI agent mode)")
print("    2 - Web UI   (browser interface)")
print("    3 - Headless (only the API, no window)")
print()

while True:
    try:
        choice = input("  Option [1/2/3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        choice = "1"
    if choice in ("1", "2", "3"):
        break
    print("  Invalid. Choose 1, 2 or 3.")

print()

MODES = {"1": "terminal", "2": "web", "3": "headless"}
mode = MODES[choice]

svc = ROOT / "scripts" / "service.py"
py = python_runtime.pythonw_exe()
env = python_runtime.child_env()

startup_kw = {}
if os.name == "nt":
    if mode != "terminal":
        startup_kw = {"creationflags": 0x08000000}
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags = subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            startup_kw["startupinfo"] = si
        except Exception:
            pass
else:
    startup_kw = {"start_new_session": True}

if mode == "terminal" and os.name != "nt":
    try:
        raise SystemExit(subprocess.call([py, str(svc), mode], env=env))
    except KeyboardInterrupt:
        raise SystemExit(0)

subprocess.Popen([py, str(svc), mode], env=env, **startup_kw)

print(f"  {mode.capitalize()} mode started.")
print("  O motor continua ativo mesmo se você fechar o navegador.")
print("  Use o indicador 'Drix — serviços' para ver e parar os serviços.")

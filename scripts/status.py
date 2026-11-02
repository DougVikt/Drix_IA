import os, sys, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.hardware as hardware
import yaml

with open(ROOT / "config" / "config.yaml") as f:
    cfg = yaml.safe_load(f)

hw = hardware.analyze()

print("=" * 50)
print("  DRIX - SYSTEM STATUS")
print("=" * 50)

print(f"\n[Hardware]")
print(f"  RAM:       {hw['ram_gb']} GB")
print(f"  CPU:       {hw['cpu_cores']} cores")

gpu = hw.get("gpu_info", {})
if gpu.get("nvidia"):
    print(f"  GPU:       NVIDIA {gpu['nvidia']['name']} ({gpu['nvidia']['vram']})")
elif gpu.get("amd"):
    print(f"  GPU:       AMD {gpu['amd']['name']}")
elif gpu.get("vulkan"):
    print(f"  GPU:       Vulkan device detected")
else:
    print(f"  GPU:       not detected (CPU mode)")

print(f"\n[Model]")
print(f"  Selected:  {hw['selected_model']}")
print(f"  Installed: {len(hw['installed_models'])} model(s)")
for m in hw["installed_models"]:
    print(f"    - {m}")

ollama_fallback = ROOT / "ia_system" / "engine" / "ollama.exe"
ollama_bin = shutil.which("ollama") or (ollama_fallback if ollama_fallback.exists() else None)
print(f"\n[Ollama]")
print(f"  Binary:    {ollama_bin or 'NOT FOUND'}")
if ollama_bin:
    try:
        r = subprocess.run(["tasklist", "/fi", "imagename eq ollama.exe"],
                          capture_output=True, text=True, timeout=5)
        running = "ollama.exe" in r.stdout
        print(f"  Running:   {'Yes' if running else 'No'}")
    except Exception:
        print(f"  Running:   ?")

print(f"\n[Storage]")
data = ROOT / "data"
if data.exists():
    total = sum(f.stat().st_size for f in data.rglob("*") if f.is_file())
    print(f"  data/:     {total / 1024:.1f} KB")
vd = ROOT / "data" / "vector_db"
if vd.exists():
    vsize = sum(f.stat().st_size for f in vd.rglob("*") if f.is_file())
    print(f"  vector_db: {vsize / 1024:.1f} KB")
logs = ROOT / "logs"
if logs.exists():
    lsize = sum(f.stat().st_size for f in logs.rglob("*") if f.is_file())
    print(f"  logs/:     {lsize / 1024:.1f} KB")
backups = ROOT / "backups"
if backups.exists():
    bsize = sum(f.stat().st_size for f in backups.rglob("*") if f.is_file())
    print(f"  backups/:  {bsize / 1024:.1f} KB")

print(f"\n[Config]")
mode = cfg.get("operation", {}).get("mode", "?")
network = cfg.get("network", {}).get("allow_internet_access", False)
print(f"  Mode:      {mode}")
print(f"  Network:   {'Enabled' if network else 'Disabled'}")
lang = cfg.get("language", "en")
print(f"  Language:  {lang}")
print()

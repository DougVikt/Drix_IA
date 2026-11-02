import sys, os, time, subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("OLLAMA_MODELS", str(_ROOT / "ia_system" / "models"))

from core import logs
logs.setup()

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.prompt import Prompt

console = Console()

BANNER = """
                ██████╗ ██████╗ ██╗██╗  ██╗
                ██╔══██╗██╔══██╗██║╚██╗██╔╝
                ██║  ██║██████╔╝██║ ╚███╔╝
                ██║  ██║██╔══██╗██║ ██╔██╗
                ██████╔╝██║  ██║██║██╔╝ ██╗
                ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝
"""


def check_hardware():
    try:
        import core.hardware as hardware
        hw = hardware.analyze()
        if not hw or "selected_model" not in hw:
            logs.warn("Hardware analysis returned incomplete data")
            return False, None
        return True, hw
    except Exception as e:
        logs.error(f"Hardware check failed: {e}")
        return False, None


def check_ollama():
    try:
        from api import engine
        if engine.port_in_use():
            pass
        else:
            ok = engine.start()
            if not ok:
                logs.warn("Ollama engine start returned False")
                return False
            engine.sync_models()
        import urllib.request, urllib.error
        for attempt in range(15):
            try:
                urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3)
                return True
            except urllib.error.URLError:
                if attempt < 14:
                    time.sleep(2)
        logs.error("Ollama API not responding after 30s")
        return False
    except Exception as e:
        logs.error(f"Ollama check failed: {e}")
        return False


def check_mem0():
    import core.memory as memory
    for attempt in range(3):
        try:
            m = memory.get_memory()
            if m is not None:
                return True
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                logs.error(f"Mem0 check failed after 3 attempts: {e}")
    return False


def warm_model(hw_data):
    model = hw_data.get("selected_model", "phi3.5:3.8b")
    try:
        import ollama
        ollama.chat(model=model, messages=[{"role": "user", "content": "ok"}],
                    options={"num_predict": 1})
        return True
    except Exception as e:
        logs.warn(f"Model pre-heat failed (non-critical): {e}")
        return False


def show_hardware_table(hw):
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    table.add_column(style="bold cyan", width=18)
    table.add_column(style="white")

    ram_color = "red" if hw["ram_gb"] < 8 else "yellow" if hw["ram_gb"] < 12 else "green"
    table.add_row("RAM:", f"[{ram_color}]{hw['ram_gb']} GB[/]")
    table.add_row("CPU:", f"{hw['cpu_cores']} cores")

    gpu_info = hw.get("gpu_info", {})
    if gpu_info.get("nvidia"):
        g = gpu_info["nvidia"]
        table.add_row("GPU:", f"NVIDIA {g['name']} ({g['vram']})")
    elif gpu_info.get("amd"):
        table.add_row("GPU:", f"AMD {gpu_info['amd']['name']}")
    elif gpu_info.get("vulkan"):
        table.add_row("GPU:", f"Vulkan ({gpu_info['vulkan']['name']})")
    else:
        table.add_row("GPU:", "[dim]not detected (CPU mode)[/]")

    return table


def show_models_table(hw):
    table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    table.add_column(style="bold cyan", width=18)
    table.add_column(style="white")

    table.add_row("Selected:", f"[bold green]{hw['selected_model']}[/]")

    models = hw.get("installed_models", [])
    if models:
        lines = "\n".join(f"  - {m}" for m in models)
        table.add_row("Installed:", lines)
    else:
        table.add_row("Installed:", "[dim](none)[/]")

    return table


def main():
    if os.name == "nt":
        try:
            print("\033[8;30;60t", end="", flush=True)
        except Exception:
            pass

    console.clear()
    console.print(Panel(Text(BANNER, style="bold cyan"), box=box.ROUNDED, title="[bold yellow]Drix[/]", subtitle="[dim]Portable AI[/]"))
    console.print()
    console.print(Text("This may take a minute..." , style="bold"))

    results = {}
    hw_data = None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("[cyan]Analyzing hardware...", total=None)
        ok, hw_data = check_hardware()
        time.sleep(0.3)
        progress.update(task, visible=False)
        results["Hardware"] = ok

        task = progress.add_task("[cyan]Starting Ollama engine...", total=None)
        results["Ollama"] = check_ollama()
        time.sleep(0.3)
        progress.update(task, visible=False)

        task = progress.add_task("[cyan]Initializing Mem0 memory...", total=None)
        results["Mem0"] = check_mem0()
        progress.update(task, visible=False)

        warmed = False
        if results["Ollama"] and hw_data:
            task = progress.add_task(f"[cyan]Pre-heating {hw_data.get('selected_model', 'model')}...", total=None)
            warmed = warm_model(hw_data)
            progress.update(task, visible=False)

    console.clear()

    result_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
    result_table.add_column(style="bold", width=14)
    result_table.add_column(style="white")
    all_ok = True
    required = {"Hardware", "Ollama"}
    for name in ("Hardware", "Ollama", "Mem0"):
        ok = results.get(name, False)
        icon = "[bold green]✔[/]" if ok else "[bold red]✘[/]"
        color = "green" if ok else "red"
        suffix = "" if name in required else " [dim](opcional)[/]"
        result_table.add_row(f"{name}:", f"[{color}]{icon}[/]{suffix}")
        if not ok and name in required:
            all_ok = False
    console.print(Panel(result_table, title="[bold]Startup Results[/]", box=box.ROUNDED, border_style="cyan"))

    if not all_ok:
        console.print()
        console.print(Panel(
            "[bold red]One or more services failed to start.[/]\n\n"
            "  Please close this window and restart Drix using [bold]start.bat[/].\n"
            "  If the problem persists, check [bold]logs/drix.log[/] for details.",
            title="[bold red]Error[/]", box=box.ROUNDED, border_style="red"
        ))
        input("\n  Press Enter to exit...")
        sys.exit(1)

    console.print()
    if hw_data:
        console.print(Panel(show_hardware_table(hw_data), title="[bold]Host Hardware[/]", box=box.ROUNDED, border_style="blue"))
        console.print()
        console.print(Panel(show_models_table(hw_data), title="[bold]Models[/]", box=box.ROUNDED, border_style="blue"))

        if hw_data["ram_gb"] < 8:
            console.print("  [yellow](!) Low RAM - expect slower responses[/]")
        if warmed:
            console.print("  [green](!) Model pre-heated for faster first response[/]")
    else:
        console.print("  [red]Hardware detection failed[/]")

    console.print()
    console.print("  [white]1 - Terminal (CLI)[/]")
    console.print("  [white]2 - Web UI[/]")
    console.print()

    choice = Prompt.ask("  [bold cyan]Choose interface[/]", choices=["1", "2"], default="2")

    svc = _ROOT / "scripts" / "service.py"
    pythonw = _ROOT / ".venv" / "Scripts" / "pythonw.exe"
    py = str(pythonw) if pythonw.exists() else sys.executable
    env = {**os.environ, "OLLAMA_MODELS": str(_ROOT / "ia_system" / "models")}

    mode_arg = "terminal" if choice == "1" else "web"
    try:
        subprocess.Popen([py, str(svc), mode_arg], env=env)
    except Exception as e:
        logs.error(f"Failed to start service.py: {e}")
        console.print(f"  [red]Error starting service: {e}[/]")
        sys.exit(1)

    if choice == "1":
        console.print("  [green]Terminal mode started in a new window.[/]")
    else:
        console.print("  [green]Web mode started. Open http://localhost:8000 in your browser.[/]")
    console.print("  [dim](service.py managing engine lifecycle - watchdog active)[/]")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        logs.error(f"Checker crashed: {e}\n{traceback.format_exc()}")
        console = Console()
        console.print(f"\n  [red]Unexpected error: {e}[/]")
        console.print("  [dim]Check logs/drix.log for details.[/]")
        input("\n  Press Enter to exit...")
        sys.exit(1)

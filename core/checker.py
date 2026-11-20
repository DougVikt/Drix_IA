import sys, os, time, subprocess, traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_DIR = Path(__file__).resolve().parent

# Running ``python core/checker.py`` puts ``core/`` first on sys.path, which
# shadows the standard-library ``secrets`` module with ``core/secrets.py``.
# FastAPI/Starlette imports ``secrets`` indirectly, so remove the script
# directory and put the project root first instead.
_clean_path = []
for _entry in sys.path:
    try:
        if _entry and Path(_entry).resolve() == _SCRIPT_DIR:
            continue
    except Exception:
        pass
    _clean_path.append(_entry)
sys.path[:] = _clean_path
sys.path.insert(0, str(_ROOT))

os.environ.setdefault("OLLAMA_MODELS", str(_ROOT / "ia_system" / "models"))

# Write a marker before importing third-party packages.  If Python itself
# fails, start.bat shows this file; if an import fails, the traceback goes to
# start.bat's stderr redirection.
try:
    _LOG_DIR = _ROOT / "logs"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(_LOG_DIR / "startup.log", "a", encoding="utf-8") as _fh:
        _fh.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] checker.py: carregando dependencias\n")
except Exception:
    pass

from core import logs
from core import python_runtime
from core import platform_paths
logs.setup()

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich import box
    from rich.prompt import Prompt
except Exception as exc:
    print()
    print("ERRO: dependencias de interface ausentes ou corrompidas.")
    print(f"Detalhe: {exc}")
    print("Restaure a pasta .venv (FastAPI, Rich, Ollama, PyTorch) ou o pacote completo da Drix.")
    if platform_paths.IS_WINDOWS:
        print("No Windows, use o pacote portatil ou rode: poetry install")
    else:
        print("No Linux, rode: ./scripts/install_linux.sh")
    print(f"Log: {_ROOT / 'logs' / 'startup.log'}")
    try:
        input("\nPressione Enter para sair...")
    except Exception:
        pass
    sys.exit(1)

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


def self_test() -> int:
    """Diagnostico rapido sem iniciar Ollama nem abrir a interface."""
    import importlib
    import shutil

    print("Drix - diagnostico de inicializacao")
    print(f"  Python:   {sys.version.split()[0]} ({sys.executable})")
    print(f"  Projeto:  {_ROOT}")
    print(f"  Portatil: {'sim' if python_runtime.has_portable_python() else 'nao (usando sys.executable)'}")

    ok = True
    try:
        venv_label = str(python_runtime.VENV_SITE.relative_to(_ROOT))
    except Exception:
        venv_label = str(python_runtime.VENV_SITE)
    ollama_label = "ia_system/engine/" + ("ollama.exe" if platform_paths.IS_WINDOWS else "ollama")
    checks = [
        ("core/checker.py", _ROOT / "core" / "checker.py", True),
        ("config/config.yaml", _ROOT / "config" / "config.yaml", True),
        (venv_label, python_runtime.VENV_SITE, platform_paths.IS_WINDOWS),
        (ollama_label, _ROOT / "ia_system" / "engine" / ("ollama.exe" if platform_paths.IS_WINDOWS else "ollama"), False),
        ("ia_system/models", _ROOT / "ia_system" / "models", False),
    ]
    for label, path, required in checks:
        exists = path.exists()
        status = "OK   " if exists else ("FALTA" if required else "AVISO")
        print(f"  {status} {label}: {path}")
        if not exists and required:
            ok = False

    modules = ["fastapi", "uvicorn", "yaml", "psutil", "httpx", "pydantic", "ollama", "rich"]
    for name in modules:
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", "?")
            print(f"  OK    import {name} {version}")
        except Exception as exc:
            ok = False
            print(f"  ERRO  import {name}: {exc}")
            traceback.print_exc()

    try:
        import api.routes  # noqa: F401
        print("  OK    import api.routes")
    except Exception as exc:
        ok = False
        print(f"  ERRO  import api.routes: {exc}")

    try:
        free = shutil.disk_usage(str(_ROOT)).free / (1024 ** 3)
        print(f"  OK    espaco livre: {free:.1f} GB")
    except Exception as exc:
        print(f"  AVISO nao foi possivel ler o disco: {exc}")

    print()
    print("Resultado:", "OK" if ok else "FALHOU")
    return 0 if ok else 1


def _pause_if_console(message: str = "\n  Press Enter to exit...") -> None:
    """Wait for Enter only when a real console is attached.

    The graphical launcher runs the checker with ``--quiet`` and no console:
    calling ``input()`` there would block forever (or raise EOFError).
    """
    try:
        if sys.stdin and sys.stdin.isatty():
            input(message)
    except Exception:
        pass


def _parse_args(argv: list[str]) -> tuple[str, bool]:
    """Return ``(mode, quiet)`` from the launcher-friendly command line."""
    mode = ""
    quiet = False
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("--mode", "-m") and index + 1 < len(argv):
            mode = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--mode="):
            mode = arg.split("=", 1)[1]
        elif arg in ("--quiet", "-q"):
            quiet = True
        index += 1
    if mode not in ("terminal", "web", "headless"):
        mode = ""
    return mode, quiet


def main():
    if "--self-test" in sys.argv:
        return self_test()

    mode_override, quiet = _parse_args(sys.argv[1:])
    platform_paths.disable_console_close()

    if not quiet:
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

    if quiet:
        ok, hw_data = check_hardware()
        results["Hardware"] = ok
        results["Ollama"] = check_ollama()
        results["Mem0"] = check_mem0()
        warmed = False
        if results["Ollama"] and hw_data:
            warmed = warm_model(hw_data)
    else:
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

    if not quiet:
        console.clear()

        result_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        result_table.add_column(style="bold", width=14)
        result_table.add_column(style="white")
        for name in ("Hardware", "Ollama", "Mem0"):
            ok = results.get(name, False)
            icon = "[bold green]✔[/]" if ok else "[bold red]✘[/]"
            color = "green" if ok else "red"
            suffix = "" if name in ("Hardware", "Ollama") else " [dim](opcional)[/]"
            result_table.add_row(f"{name}:", f"[{color}]{icon}[/]{suffix}")
        console.print(Panel(result_table, title="[bold]Startup Results[/]", box=box.ROUNDED, border_style="cyan"))

    all_ok = all(results.get(name, False) for name in ("Hardware", "Ollama"))

    if not all_ok:
        if not quiet:
            console.print()
            launcher = "start.bat" if platform_paths.IS_WINDOWS else "./start.sh"
            console.print(Panel(
                "[bold red]One or more services failed to start.[/]\n\n"
                f"  Please close this window and restart Drix using [bold]{launcher}[/].\n"
                "  If the problem persists, check [bold]logs/drix.log[/] for details.",
                title="[bold red]Error[/]", box=box.ROUNDED, border_style="red"
            ))
            _pause_if_console()
        sys.exit(1)

    if not quiet:
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
        console.print("  [white]3 - Headless (web server only)[/]")
        console.print()

    choice = {"terminal": "1", "web": "2", "headless": "3"}.get(mode_override)
    if not choice:
        choice = "2" if quiet else Prompt.ask("  [bold cyan]Choose interface[/]", choices=["1", "2", "3"], default="2")

    svc = _ROOT / "scripts" / "service.py"
    py = python_runtime.pythonw_exe()
    env = python_runtime.child_env()
    log_path = _ROOT / "logs" / "service_stderr.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    mode_arg = {"1": "terminal", "2": "web", "3": "headless"}[choice]

    # On Linux the terminal client must keep the user's terminal (stdin/stdout);
    # detaching it like on Windows would leave an invisible prompt.
    if mode_arg == "terminal" and not platform_paths.IS_WINDOWS:
        try:
            return subprocess.call([py, str(svc), mode_arg], cwd=str(_ROOT), env=env)
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            logs.error(f"Failed to start service.py: {e}")
            if not quiet:
                console.print(f"  [red]Error starting service: {e}[/]")
                console.print(f"  [dim]Veja {log_path}[/]")
            return 1

    try:
        service_log = open(log_path, "a", encoding="utf-8", buffering=1)
        proc = subprocess.Popen(
            [py, str(svc), mode_arg],
            cwd=str(_ROOT),
            env=env,
            stdout=service_log,
            stderr=service_log,
            stdin=subprocess.DEVNULL,
            **platform_paths.detach_kwargs(),
        )
        service_log.close()  # the child keeps its own handle
    except Exception as e:
        logs.error(f"Failed to start service.py: {e}")
        if not quiet:
            console.print(f"  [red]Error starting service: {e}[/]")
            console.print(f"  [dim]Veja {log_path}[/]")
        _pause_if_console()
        sys.exit(1)

    # pythonw.exe can fail before writing anything (missing DLL, import
    # error).  Wait a little and surface the failure instead of a false OK.
    deadline = time.time() + 8.0
    while time.time() < deadline and proc.poll() is None:
        time.sleep(0.25)

    if proc.poll() is not None:
        logs.error(f"service.py exited immediately with code {proc.returncode}")
        if not quiet:
            console.print()
            console.print(Panel(
                f"[bold red]O servico da Drix encerrou logo apos iniciar.[/]\n\n"
                f"Codigo: {proc.returncode}\n"
                f"Log do servico:   {log_path}\n"
                f"Log da aplicacao: {_ROOT / 'logs' / 'drix.log'}\n\n"
                "As ultimas linhas do log aparecem abaixo.",
                title="[bold red]Falha ao iniciar[/]", box=box.ROUNDED, border_style="red"
            ))
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                if lines:
                    console.print("\n".join(lines))
            except Exception:
                pass
        _pause_if_console()
        sys.exit(1)

    if not quiet:
        if choice == "1":
            console.print("  [green]Terminal mode started in a new window.[/]")
        elif choice == "3":
            console.print("  [green]Headless mode started (web server only, no browser/indicator).[/]")
            console.print("  [dim]Open http://localhost:8000 in a browser or use the API.[/]")
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
        _pause_if_console()
        sys.exit(1)

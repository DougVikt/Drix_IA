#!/usr/bin/env bash
# Install Drix's Python environment on Linux/macOS.
#
# It prefers Poetry (the project's official workflow) and falls back to pip
# using the dependencies declared in pyproject.toml.

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "ERRO: $PYTHON nao encontrado."
    echo "Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip python3-tk"
    echo "Fedora:        sudo dnf install python3 python3-pip python3-tkinter"
    exit 1
fi

if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "ERRO: a Drix exige Python 3.10+ (encontrado: $("$PYTHON" -V 2>&1))."
    exit 1
fi

VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
case "$VERSION" in
    3.12|3.13)
        echo "AVISO: Python $VERSION pode nao ter wheels para onnxruntime==1.16.3."
        echo "       Se a instalacao falhar, use Python 3.10 ou 3.11."
        ;;
esac

VENV_PY="$ROOT/.venv/bin/python"

install_with_pip() {
    if [ ! -x "$VENV_PY" ]; then
        echo "Criando .venv..."
        "$PYTHON" -m venv "$ROOT/.venv"
    fi
    "$VENV_PY" -m pip install --upgrade pip setuptools wheel
    echo "Instalando dependencias do pyproject.toml com pip..."
    "$VENV_PY" - <<'PY' > "$ROOT/.venv/drix-requirements.txt"
import re
from pathlib import Path

text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", text, re.S | re.M)
if not match:
    raise SystemExit("bloco [project].dependencies nao encontrado em pyproject.toml")
for dep in re.findall(r'"([^"]+)"', match.group(1)):
    print(dep)
PY
    "$VENV_PY" -m pip install -r "$ROOT/.venv/drix-requirements.txt"
}

if command -v poetry >/dev/null 2>&1 && [ -f "$ROOT/poetry.lock" ]; then
    echo "Instalando dependencias com Poetry (venv dentro do projeto)..."
    # Poetry creates virtualenvs in its cache by default, but start.sh uses
    # .venv/bin/python.  Force the in-project venv so both point to the same
    # interpreter.
    if POETRY_VIRTUALENVS_IN_PROJECT=true poetry install --no-root && [ -x "$VENV_PY" ]; then
        :
    else
        echo "AVISO: Poetry falhou ou nao criou .venv/bin/python; usando pip."
        install_with_pip
    fi
else
    echo "Poetry nao encontrado (ou poetry.lock ausente); usando pip."
    install_with_pip
fi

echo
echo "Verificando imports principais..."
"$VENV_PY" - <<'PY'
import importlib
missing = []
for name in ("fastapi", "uvicorn", "yaml", "httpx", "psutil", "rich"):
    try:
        importlib.import_module(name)
        print(f"  OK   {name}")
    except Exception as exc:
        missing.append(f"{name}: {exc}")
        print(f"  ERRO {name}: {exc}")
try:
    import tkinter  # noqa: F401
    print("  OK   tkinter (indicador desktop)")
except Exception:
    print("  AVISO tkinter ausente; o indicador desktop nao abrira (sudo apt install python3-tk)")
if missing:
    raise SystemExit("Dependencias ausentes: " + ", ".join(missing))
PY

echo
# Garante que scripts e binarios copiados do Windows possam ser executados.
chmod +x "$ROOT/start.sh" "$ROOT/scripts/install_linux.sh" 2>/dev/null || true
for bin in "$ROOT/ia_system/engine/ollama" "$ROOT/ia_system/bin/pmtiles" "$ROOT/ia_system/bin/ffmpeg" "$ROOT/ia_system/ffmpeg/ffmpeg"; do
    [ -f "$bin" ] && chmod +x "$bin" 2>/dev/null || true
done

echo "Ambiente pronto. Inicie com: ./start.sh"

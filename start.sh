#!/usr/bin/env bash
# Drix launcher for Linux and macOS.
#
# Usage:
#   ./start.sh            # asks for the interface (web/terminal/headless)
#   ./start.sh --self-test
#
# The Windows launcher (start.bat) remains the supported path on Windows.

set -u

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$ROOT" || exit 1

LOG="$ROOT/logs/startup.log"
mkdir -p "$ROOT/logs" || true

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG" 2>/dev/null || true
}

if [ -x "$ROOT/.venv/bin/python" ]; then
    PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
else
    echo
    echo " ERRO: Python 3.10+ nao encontrado."
    echo " Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip python3-tk"
    echo " Fedora:        sudo dnf install python3 python3-pip python3-tkinter"
    echo
    exit 1
fi

if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo " ERRO: a Drix exige Python 3.10+ (encontrado: $("$PY" -V 2>&1))."
    exit 1
fi

export OLLAMA_MODELS="${OLLAMA_MODELS:-$ROOT/ia_system/models}"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export PATH="$ROOT/ia_system/engine:$ROOT/ia_system/bin:$PATH"

if [ ! -f "$ROOT/core/checker.py" ]; then
    echo " ERRO: core/checker.py nao encontrado."
    echo " O pacote da Drix esta incompleto ou foi movido sem a pasta core."
    log "ERRO: core/checker.py ausente"
    exit 1
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo " AVISO: .venv nao encontrado; usando $PY"
    echo " Execute scripts/install_linux.sh para criar o ambiente e instalar as dependencias."
fi

if [ ! -x "$ROOT/ia_system/engine/ollama" ] && ! command -v ollama >/dev/null 2>&1; then
    echo " AVISO: Ollama nao encontrado (ia_system/engine/ollama ou PATH)."
    echo " Instale em https://ollama.com/download/linux ou copie o binario para ia_system/engine/ollama"
fi

log "start.sh: iniciando Drix ($PY)"
exec "$PY" -u "$ROOT/core/checker.py" "$@" 2>>"$LOG"

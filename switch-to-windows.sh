#!/usr/bin/env bash
#
# switch-to-windows.sh
# ---------------------
# Troca o proximo boot (e o padrao) para o Windows via ordem de boot UEFI.
#
# Uso:
#   sudo ./switch-to-windows.sh            # so troca a ordem e mostra o resultado
#   sudo ./switch-to-windows.sh --reboot   # troca e reinicia
#
# Precisa do pacote efibootmgr:
#   Debian/Ubuntu: sudo apt install efibootmgr
#   Fedora:        sudo dnf install efibootmgr
#   Arch:          sudo pacman -S efibootmgr
#
set -euo pipefail

REBOOT=0
for arg in "$@"; do
  case "$arg" in
    --reboot|-r) REBOOT=1 ;;
    -h|--help)
      grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'
      exit 0
      ;;
    *)
      echo "Argumento desconhecido: $arg" >&2
      exit 2
      ;;
  esac
done

# ---- Checagens ----------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
  echo "Execute como root:  sudo $0" >&2
  exit 1
fi

if ! command -v efibootmgr >/dev/null 2>&1; then
  echo "efibootmgr nao encontrado. Instale primeiro (ex.: sudo apt install efibootmgr)." >&2
  exit 1
fi

# Sistema tem que ser UEFI
if [ ! -d /sys/firmware/efi ]; then
  echo "Este sistema nao esta em modo UEFI. O script nao se aplica." >&2
  exit 1
fi

# ---- Descobrir a entrada do Windows ------------------------------------------

WIN_NUM="$(
  efibootmgr -v 2>/dev/null \
  | grep -iE 'Windows Boot Manager' \
  | sed -nE 's/^Boot([0-9A-Fa-f]{4})\*? .*/\1/p' \
  | head -n1
)"

if [ -z "${WIN_NUM:-}" ]; then
  echo "Nao encontrei a entrada 'Windows Boot Manager'. Entradas atuais:" >&2
  echo
  efibootmgr
  echo
  echo "Dica: copie o numero BootXXXX do Windows e rode:  sudo efibootmgr -o XXXX,<resto>" >&2
  exit 1
fi

# ---- Reordenar: Windows primeiro, mantendo o resto ---------------------------

CUR_ORDER="$(efibootmgr | sed -nE 's/^BootOrder: //p')"

REST="$(
  echo "$CUR_ORDER" \
  | tr ',' '\n' \
  | grep -viE "^${WIN_NUM}$" \
  | grep -v '^$' \
  | paste -sd, -
)"

if [ -n "$REST" ]; then
  NEW_ORDER="${WIN_NUM},${REST}"
else
  NEW_ORDER="${WIN_NUM}"
fi

echo "Entrada do Windows : Boot${WIN_NUM}"
echo "BootOrder atual    : ${CUR_ORDER:-<vazio>}"
echo "BootOrder novo     : ${NEW_ORDER}"
echo

efibootmgr -o "$NEW_ORDER"

echo
echo "OK! O proximo boot vai para o Windows (e ele fica como padrao)."
echo "Entradas apos a troca:"
efibootmgr

if [ "$REBOOT" -eq 1 ]; then
  echo
  echo "Reiniciando em 5 segundos... (Ctrl+C para cancelar)"
  sleep 5
  systemctl reboot
fi

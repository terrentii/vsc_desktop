#!/usr/bin/env bash
#
# Удаление МЫС Desktop. Зеркало install.sh.
#
#   ./packaging/uninstall.sh             # удалить пользовательскую установку
#   sudo ./packaging/uninstall.sh --system   # удалить системную установку
#
# По умолчанию НЕ трогает данные пользователя (зашифрованный vault в
# ~/.local/share/mys). Чтобы удалить и их — флаг --purge.
#
set -euo pipefail

MODE="user"
PURGE=0
APP_ID="mys-desktop"

for arg in "$@"; do
    case "$arg" in
        --system) MODE="system" ;;
        --purge)  PURGE=1 ;;
        --help|-h) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный аргумент: $arg" >&2; exit 2 ;;
    esac
done

c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }

if [ "$MODE" = "system" ]; then
    [ "$(id -u)" -eq 0 ] || { echo "Режим --system требует root." >&2; exit 1; }
    APP_DIR="/opt/$APP_ID"
    BIN_DIR="/usr/local/bin"
    DESKTOP_DIR="/usr/share/applications"
    ICON_ROOT="/usr/share/icons/hicolor"
else
    APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
    BIN_DIR="$HOME/.local/bin"
    DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    ICON_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
fi

rm -f  "$BIN_DIR/$APP_ID"                  && c_ok "Лаунчер удалён"
rm -f  "$DESKTOP_DIR/$APP_ID.desktop"      && c_ok "Ярлык удалён"
for size in 16 32 48 64 128 256; do
    rm -f "$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
done
c_ok "Иконки удалены"
rm -rf "$APP_DIR"                          && c_ok "Окружение удалено ($APP_DIR)"

command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f "$ICON_ROOT" 2>/dev/null || true

if [ "$PURGE" -eq 1 ]; then
    DATA="${XDG_DATA_HOME:-$HOME/.local/share}/mys"
    rm -rf "$DATA" && c_warn "Данные пользователя удалены ($DATA) — vault и история стёрты."
else
    echo
    c_warn "Данные пользователя (зашифрованный vault) сохранены в ~/.local/share/mys"
    c_warn "Чтобы удалить и их: $0 --purge"
fi
echo
c_ok "МЫС Desktop удалён."

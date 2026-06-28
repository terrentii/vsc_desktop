#!/usr/bin/env bash
#
# Нативная установка МЫС Desktop в Linux.
#
# По умолчанию ставит для текущего пользователя (без root): изолированный venv,
# ярлык в меню приложений и иконку — так же, как ведёт себя обычное GUI-приложение.
#
#   ./packaging/install.sh              # для текущего пользователя (рекомендуется)
#   sudo ./packaging/install.sh --system   # для всех пользователей системы
#   ./packaging/install.sh --deps       # попытаться доустановить системные зависимости
#
# Опции:
#   --system   установить в /opt + /usr (нужен root)
#   --deps     доустановить системные пакеты (libsodium и т.п.) через пакетный менеджер
#   --help     показать справку
#
set -euo pipefail

# --- параметры -------------------------------------------------------------
MODE="user"
WITH_DEPS=0
APP_ID="mys-desktop"

for arg in "$@"; do
    case "$arg" in
        --system) MODE="system" ;;
        --deps)   WITH_DEPS=1 ;;
        --help|-h)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "Неизвестный аргумент: $arg (см. --help)" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- вывод -----------------------------------------------------------------
c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
c_info() { printf '\033[36m•\033[0m %s\n' "$*"; }
c_warn() { printf '\033[33m!\033[0m %s\n' "$*"; }
c_err()  { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }
die()    { c_err "$*"; exit 1; }

# --- определить пути установки ---------------------------------------------
if [ "$MODE" = "system" ]; then
    [ "$(id -u)" -eq 0 ] || die "Режим --system требует root. Запусти: sudo $0 --system"
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
VENV="$APP_DIR/venv"
LAUNCHER="$BIN_DIR/$APP_ID"

c_info "Режим установки: $MODE"
c_info "Каталог приложения: $APP_DIR"

# --- системные зависимости -------------------------------------------------
detect_pm() {
    for pm in pacman apt-get dnf zypper; do
        command -v "$pm" >/dev/null 2>&1 && { echo "$pm"; return; }
    done
}

deps_hint() {
    case "$1" in
        pacman)  echo "sudo pacman -S --needed libsodium python" ;;
        apt-get) echo "sudo apt-get install -y libsodium23 python3-venv python3-dev" ;;
        dnf)     echo "sudo dnf install -y libsodium python3" ;;
        zypper)  echo "sudo zypper install -y libsodium23 python3" ;;
        *)       echo "(установи libsodium >= 1.0.18 и python3-venv средствами своего дистрибутива)" ;;
    esac
}

install_deps() {
    local pm; pm="$(detect_pm)"
    [ -n "$pm" ] || die "Не удалось определить пакетный менеджер. Установи зависимости вручную."
    c_info "Устанавливаю системные зависимости через $pm…"
    local sudo=""; [ "$(id -u)" -eq 0 ] || sudo="sudo"
    case "$pm" in
        pacman)  $sudo pacman -S --needed --noconfirm libsodium python ;;
        apt-get) $sudo apt-get update && $sudo apt-get install -y libsodium23 python3-venv python3-dev ;;
        dnf)     $sudo dnf install -y libsodium python3 ;;
        zypper)  $sudo zypper install -y libsodium23 python3 ;;
    esac
}

[ "$WITH_DEPS" -eq 1 ] && install_deps

# libsodium обязателен (крипто-ядро CPace грузит его через ctypes)
if ! ldconfig -p 2>/dev/null | grep -qi 'libsodium'; then
    c_warn "libsodium не найден в системе."
    c_warn "Установи его: $(deps_hint "$(detect_pm)")"
    c_warn "…или перезапусти с флагом --deps. Без libsodium P2P-режим работать не будет."
    die "Прерываю: нет libsodium."
fi
c_ok "libsodium найден"

# Python 3.13+
command -v python3 >/dev/null 2>&1 || die "python3 не найден."
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,13) else 1)' \
    || die "Нужен Python 3.13+, найден $PYV."
c_ok "Python $PYV"

# --- venv + установка пакета ----------------------------------------------
c_info "Создаю изолированное окружение в $VENV…"
mkdir -p "$APP_DIR"
python3 -m venv "$VENV" || die "Не удалось создать venv (нужен пакет python3-venv?)."
"$VENV/bin/python" -m pip install --upgrade pip wheel >/dev/null
c_info "Устанавливаю МЫС Desktop и зависимости (PySide6 и пр. — может занять время)…"
"$VENV/bin/python" -m pip install "$REPO_ROOT"
c_ok "Пакет установлен в окружение"

# --- лаунчер ---------------------------------------------------------------
mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Запуск МЫС Desktop из изолированного окружения.
exec "$VENV/bin/mys-desktop" "\$@"
EOF
chmod +x "$LAUNCHER"
c_ok "Лаунчер: $LAUNCHER"

# --- иконки ----------------------------------------------------------------
for size in 16 32 48 64 128 256; do
    src="$SCRIPT_DIR/icons/hicolor/${size}x${size}/apps/$APP_ID.png"
    dst="$ICON_ROOT/${size}x${size}/apps/$APP_ID.png"
    [ -f "$src" ] || continue
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
done
c_ok "Иконки установлены в $ICON_ROOT"

# --- .desktop --------------------------------------------------------------
mkdir -p "$DESKTOP_DIR"
DESKTOP_FILE="$DESKTOP_DIR/$APP_ID.desktop"
# Exec прописываем абсолютным путём к лаунчеру — меню запускает без учёта PATH.
sed "s|^Exec=.*|Exec=$LAUNCHER|" "$SCRIPT_DIR/$APP_ID.desktop" > "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"
c_ok "Ярлык: $DESKTOP_FILE"

# --- обновить кэши рабочего стола ------------------------------------------
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f "$ICON_ROOT" 2>/dev/null || true

echo
c_ok "Готово! «МЫС Desktop» установлен."
echo "  • Запуск из меню приложений (раздел «Интернет / Сеть»)."
echo "  • Или из терминала: $APP_ID"
if [ "$MODE" = "user" ] && ! echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
    echo
    c_warn "$BIN_DIR не в \$PATH — команда из терминала не найдётся (ярлык в меню работает в любом случае)."
    c_warn "Добавь в ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
echo
echo "Удаление: $SCRIPT_DIR/uninstall.sh${MODE:+ }$([ "$MODE" = system ] && echo --system)"

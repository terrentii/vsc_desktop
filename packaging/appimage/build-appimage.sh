#!/usr/bin/env bash
#
# Собрать AppImage МЫС Desktop (Linux x86_64).
#
# AppImage — один самодостаточный файл «скачал и запустил», без установки и без
# root: внутри изолированный Python нужной версии, все pip-зависимости (PySide6
# и пр.) и bundled libsodium. Работает на большинстве современных дистрибутивов.
#
#   ./packaging/appimage/build-appimage.sh            # python 3.13 по умолчанию
#   ./packaging/appimage/build-appimage.sh --python 3.13
#
# Результат: dist/МЫС Desktop-x86_64.AppImage
#
set -euo pipefail

PYVER="3.13"
while [ $# -gt 0 ]; do
    case "$1" in
        --python) PYVER="$2"; shift 2 ;;
        --help|-h) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST="$REPO_ROOT/dist"
APP_ID="mys-desktop"

c_info() { printf '\033[36m•\033[0m %s\n' "$*"; }
c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
die()    { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null || die "нужен python3"
mkdir -p "$DIST"

# --- инструменты сборки в одноразовом venv --------------------------------
BUILD_VENV="$(mktemp -d)/venv"
c_info "Готовлю окружение сборки…"
python3 -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/pip" install --quiet --upgrade pip build python-appimage

# --- wheel приложения ------------------------------------------------------
c_info "Собираю wheel…"
rm -f "$DIST"/mys_desktop-*.whl
"$BUILD_VENV/bin/python" -m build --wheel --outdir "$DIST" "$REPO_ROOT" >/dev/null
WHEEL="$(ls "$DIST"/mys_desktop-*.whl | head -1)"
[ -n "$WHEEL" ] || die "wheel не собрался"
c_ok "wheel: $(basename "$WHEEL")"

# --- recipe для python-appimage -------------------------------------------
# Имя каталога-рецепта = имя приложения (так требует python-appimage).
RECIPE="$(mktemp -d)/$APP_ID"
mkdir -p "$RECIPE"
cp "$REPO_ROOT/packaging/$APP_ID.desktop"                       "$RECIPE/$APP_ID.desktop"
cp "$REPO_ROOT/packaging/icons/hicolor/256x256/apps/$APP_ID.png" "$RECIPE/$APP_ID.png"
cp "$SCRIPT_DIR/entrypoint.sh"                                   "$RECIPE/entrypoint.sh"
# requirements: ставим именно наш wheel — pip дотянет зависимости с PyPI.
printf '%s\n' "$WHEEL" > "$RECIPE/requirements.txt"

# --- bundled libsodium -----------------------------------------------------
# Крипто-ядро (CPace) грузит libsodium через ctypes — кладём его внутрь AppImage,
# чтобы P2P-режим работал и там, где libsodium в системе нет.
LIBS="$(mktemp -d)/libs"
mkdir -p "$LIBS"
# Полный вывод ldconfig сначала в переменную: awk с ранним exit закрыл бы пайп и
# уронил ldconfig по SIGPIPE (под set -o pipefail это завалило бы весь скрипт).
LDOUT="$(ldconfig -p 2>/dev/null || true)"
SODIUM="$(printf '%s\n' "$LDOUT" | awk '/libsodium\.so\.[0-9]+/{print $NF; exit}')" || true
if [ -n "$SODIUM" ] && [ -f "$SODIUM" ]; then
    cp -L "$SODIUM" "$LIBS/$(basename "$SODIUM")"
    c_ok "bundled $(basename "$SODIUM")"
else
    printf '\033[33m!\033[0m libsodium не найден в системе — AppImage будет полагаться на libsodium хоста.\n'
fi

# --- сборка AppDir (без упаковки) ------------------------------------------
# python-appimage упаковал бы сам, но передаёт имя файла из Name= (.desktop) в
# shell-команду appimagetool без кавычек — пробел/кириллица в «МЫС Desktop» ломают
# вызов. Поэтому собираем только AppDir, а упаковку делаем сами с корректным
# ASCII-именем (отображаемое имя в .desktop при этом остаётся «МЫС Desktop»).
# Позиционный appdir — первым: иначе -x (nargs='+') «съедает» путь к рецепту.
ARCH_NAME="$(uname -m)"
c_info "Собираю AppDir (python $PYVER)…"
cd "$DIST"
rm -rf "$DIST"/*-"$ARCH_NAME"
APPIMAGE_EXTRACT_AND_RUN=1 "$BUILD_VENV/bin/python" -m python_appimage build app \
    "$RECIPE" -p "$PYVER" -x "$LIBS" --no-packaging
APPDIR_DIR="$(find "$DIST" -maxdepth 1 -type d -name "*-$ARCH_NAME" | head -1)"
[ -n "$APPDIR_DIR" ] || die "AppDir не собран"

# --- упаковка AppDir → AppImage --------------------------------------------
c_info "Упаковываю в AppImage…"
TOOL="$(mktemp -d)/appimagetool"
wget -qO "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH_NAME}.AppImage"
chmod +x "$TOOL"
OUT="$DIST/MYS_Desktop-${ARCH_NAME}.AppImage"
rm -f "$OUT"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH_NAME" "$TOOL" --no-appstream "$APPDIR_DIR" "$OUT"
rm -rf "$APPDIR_DIR"
[ -f "$OUT" ] || die "AppImage не создан"
chmod +x "$OUT"
echo
c_ok "Готово: $OUT"
echo "  Запуск:  \"$OUT\""
echo "  (на старых системах без FUSE:  \"$OUT\" --appimage-extract-and-run)"

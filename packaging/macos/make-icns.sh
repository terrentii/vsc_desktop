#!/usr/bin/env bash
#
# Сгенерировать packaging/macos/mys-desktop.icns из исходной иконки.
#
# На macOS использует нативный iconutil (правильный .icns с набором размеров).
# На других ОС — fallback через png2icns или ImageMagick (для локальной проверки).
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="$REPO_ROOT/src/mys_ui/vsc.ico"
OUT="$SCRIPT_DIR/mys-desktop.icns"

if command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
    TMP="$(mktemp -d)/mys.iconset"
    mkdir -p "$TMP"
    # Базовый PNG 1024×1024 из исходника.
    sips -s format png "$SRC" --out "$TMP/base.png" >/dev/null
    sips -z 1024 1024 "$TMP/base.png" --out "$TMP/base.png" >/dev/null
    for pair in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" "64 icon_32x32@2x" \
                "128 icon_128x128" "256 icon_128x128@2x" "256 icon_256x256" \
                "512 icon_256x256@2x" "512 icon_512x512" "1024 icon_512x512@2x"; do
        set -- $pair
        sips -z "$1" "$1" "$TMP/base.png" --out "$TMP/$2.png" >/dev/null
    done
    iconutil -c icns "$TMP" -o "$OUT"
elif command -v png2icns >/dev/null 2>&1; then
    TMP="$(mktemp -d)"
    for s in 16 32 48 128 256 512; do
        magick "$SRC" -background none -resize ${s}x${s} -gravity center -extent ${s}x${s} "$TMP/$s.png"
    done
    png2icns "$OUT" "$TMP"/*.png
else
    echo "Нужен iconutil (macOS) или png2icns. На macOS-раннере CI это есть." >&2
    exit 1
fi
echo "Готово: $OUT"

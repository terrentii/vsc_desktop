#!/usr/bin/env bash
#
# Собрать AppImage МЫС Desktop (Linux x86_64).
#
# AppImage — один самодостаточный файл «скачал и запустил»: внутри переносимый
# CPython (python-build-standalone), все pip-зависимости и нативные библиотеки
# (libsodium, libzstd, xcb-util). Работает на дистрибутивах с glibc ≥ 2.35
# (Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+, Arch, NixOS через appimage-run).
#
#   ./packaging/appimage/build-appimage.sh
#
# Нужны: curl, tar, zstd, xz, python3, mksquashfs (squashfs-tools). На NixOS скрипт сам запускает
# переносимый Python через steam-run (FHS), а mksquashfs можно взять так:
#   nix shell nixpkgs#squashfsTools --command ./packaging/appimage/build-appimage.sh
#
# Результат: dist/MYS_Desktop-x86_64.AppImage
#
# Упаковку делаем сами (runtime + squashfs), без appimagetool/python-appimage:
# они сами AppImage и на NixOS перехватываются binfmt, а runtime из «continuous»
# уже давал битый образ. Версии ниже закреплены и проверены.
set -euo pipefail

PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20260924/cpython-3.13.15%2B20260924-x86_64-unknown-linux-gnu-install_only.tar.gz"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"

case "${1:-}" in
    --help|-h) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST="$REPO_ROOT/dist"
APP_ID="mys-desktop"
OUT="$DIST/MYS_Desktop-x86_64.AppImage"

c_info() { printf '\033[36m•\033[0m %s\n' "$*"; }
c_ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }
die()    { printf '\033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -m)" = x86_64 ] || die "поддерживается только x86_64"
for t in curl tar zstd xz python3 mksquashfs; do command -v "$t" >/dev/null || die "нужен $t"; done

# Переносимый Python динамически линкуется с /lib64/ld-linux — на NixOS его нет,
# поэтому там гоняем его внутри FHS-окружения steam-run.
RUN=()
if [ -e /etc/NIXOS ]; then
    command -v steam-run >/dev/null || die "на NixOS нужен steam-run (programs.steam или pkgs.steam-run)"
    RUN=(steam-run)
fi

# Рабочий каталог — не в /tmp: steam-run подменяет /tmp своим.
mkdir -p "$DIST"
WORK="$(mktemp -d "$DIST/.build.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
APPDIR="$WORK/AppDir"
mkdir -p "$APPDIR/usr/lib"

# --- переносимый CPython ----------------------------------------------------
c_info "Скачиваю Python…"
curl -fsSL "$PY_URL" | tar -xz -C "$APPDIR/usr"   # → usr/python/
PY="$APPDIR/usr/python/bin/python3"

# --- приложение и зависимости ----------------------------------------------
c_info "Ставлю приложение и зависимости…"
"${RUN[@]}" "$PY" -m pip install --quiet --disable-pip-version-check \
    --no-warn-script-location "$REPO_ROOT"
"${RUN[@]}" "$PY" -c "import PySide6.QtWidgets, sqlcipher3, cryptography, argon2, httpx, websockets, mys_ui" \
    || die "зависимости не импортируются"

# --- облегчение: приложению нужны только QtCore/QtGui/QtWidgets --------------
# ponytail: белый список по именам; новый импорт PySide6.QtXxx — добавить его
# в оба списка ниже, иначе в AppImage модуля не будет.
SP="$("${RUN[@]}" "$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
QT="$SP/PySide6/Qt"
rm -rf "$QT/qml" "$QT/translations" "$QT/metatypes" "$QT/libexec" \
       "$SP/pip" "$SP"/pip-*.dist-info "$APPDIR/usr/python/lib/python3.13/test" \
       "$APPDIR/usr/python/include"
# Qt/lib — белый список; плагины, тянущие удалённые модули, — тоже вон.
find "$QT/lib" -maxdepth 1 -name 'lib*.so*' \
    ! -name 'libicu*' ! -name 'libQt6Core.*' ! -name 'libQt6Gui.*' ! -name 'libQt6Widgets.*' \
    ! -name 'libQt6DBus.*' ! -name 'libQt6Network.*' ! -name 'libQt6OpenGL.*' \
    ! -name 'libQt6XcbQpa.*' ! -name 'libQt6WaylandClient.*' ! -name 'libQt6WlShellIntegration.*' \
    ! -name 'libQt6EglFS*' ! -name 'libQt6PrintSupport.*' -delete
rm -rf "$QT"/plugins/{designer,qmltooling,sqldrivers,vectorimageformats,wayland-graphics-integration-server}
find "$SP/PySide6" -maxdepth 1 -type f \( -name 'Qt*.abi3.so' -o -name 'libpyside6qml*' \) \
    ! -name 'QtCore.*' ! -name 'QtGui.*' ! -name 'QtWidgets.*' ! -name 'QtNetwork.*' \
    ! -name 'QtDBus.*' ! -name 'QtOpenGL.*' -delete
find "$SP/PySide6" -maxdepth 1 -type f -perm -u+x ! -name '*.so*' -delete  # designer, uic, …
find "$APPDIR/usr/python/bin" -name 'pip*' -delete

# --- bundled нативные библиотеки ---------------------------------------------
# Берём из закреплённых пакетов Ubuntu 22.04 (glibc 2.35): сборка герметична и
# одинакова на любом хосте, а библиотеки грузятся на любом дистрибутиве не старше.
#   libsodium — крипто-ядру (CPace через ctypes), без него приложение не стартует;
#   libzstd   — QtCore (нет в appimage-run на NixOS);
#   xcb-util* — X11-плагину Qt ≥6.5 (часто нет на Ubuntu/Mint/Debian).
c_info "Докладываю нативные библиотеки…"
DEBS=(
    main/libs/libsodium/libsodium23_1.0.18-1build2_amd64.deb
    main/libz/libzstd/libzstd1_1.4.8+dfsg-3build1_amd64.deb
    universe/x/xcb-util-cursor/libxcb-cursor0_0.1.1-4ubuntu1_amd64.deb
    main/x/xcb-util-wm/libxcb-icccm4_0.4.1-1.1build2_amd64.deb
    main/x/xcb-util-image/libxcb-image0_0.4.0-2_amd64.deb
    main/x/xcb-util-keysyms/libxcb-keysyms1_0.4.0-1build3_amd64.deb
    main/x/xcb-util-renderutil/libxcb-render-util0_0.3.9-1build3_amd64.deb
    main/x/xcb-util/libxcb-util1_0.4.0-1build2_amd64.deb
    # libxkbcommon-x11 НЕ кладём: он обязан совпадать по версии с системным
    # libxkbcommon — старый из пакета с новым системным даёт segfault на X11.
)
mkdir -p "$WORK/deb"
for d in "${DEBS[@]}"; do
    curl -fsSL --retry 5 --retry-all-errors -o "$WORK/pkg.deb" "http://archive.ubuntu.com/ubuntu/pool/$d"
    # .deb — ar-архив; достаём data.tar.{zst,xz} без dpkg/ar, сжатие tar определит сам.
    data="$(python3 - "$WORK/pkg.deb" "$WORK" <<'EOF'
import os, sys
d = open(sys.argv[1], "rb").read()
i = 8
while i < len(d):
    name, size = d[i:i + 16].strip().decode().rstrip("/"), int(d[i + 48:i + 58])
    if name.startswith("data.tar"):
        out = os.path.join(sys.argv[2], name)
        open(out, "wb").write(d[i + 60:i + 60 + size])
        print(out)
        break
    i += 60 + size + (size & 1)
EOF
)"
    tar -xf "$data" -C "$WORK/deb"
done
cp -P "$WORK"/deb/usr/lib/x86_64-linux-gnu/*.so.* "$APPDIR/usr/lib/"
c_ok "$(ls "$APPDIR/usr/lib" | wc -l) файлов в usr/lib"

# Самопроверка AppDir: импорт GUI после чистки + CPace на упакованном libsodium.
"${RUN[@]}" env LD_LIBRARY_PATH="$APPDIR/usr/lib" MYS_LIBSODIUM="$APPDIR/usr/lib/libsodium.so.23" \
    "$PY" -I -c "
import PySide6.QtWidgets, mys_ui.app
from mys_crypto import pake
a, ya = pake.cpace_msg(b'prs', b'sid'); b, yb = pake.cpace_msg(b'prs', b'sid')
assert pake.cpace_finish(a, yb) == pake.cpace_finish(b, ya)
" || die "самопроверка AppDir не прошла"
c_ok "самопроверка AppDir"

# --- обвязка AppDir ----------------------------------------------------------
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="$HERE/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export MYS_LIBSODIUM="$HERE/usr/lib/libsodium.so.23"
# У переносимого OpenSSL нет пути к системным CA: httpx берёт certifi сам, а
# websockets (wss:// — real-time «Центра» и P2P) без этого падает на проверке TLS.
export SSL_CERT_FILE="${SSL_CERT_FILE:-$HERE/usr/python/lib/python3.13/site-packages/certifi/cacert.pem}"
# шумные, но безобидные предупреждения Qt Wayland о поле ввода
export QT_LOGGING_RULES="${QT_LOGGING_RULES:-qt.qpa.wayland.textinput=false}"
# -I: изолированный режим — игнорировать PYTHON*-переменные и user site-packages хоста.
exec "$HERE/usr/python/bin/python3" -I -m mys_ui "$@"
EOF
chmod +x "$APPDIR/AppRun"
[ -f "$APPDIR/usr/python/lib/python3.13/site-packages/certifi/cacert.pem" ] \
    || die "нет certifi/cacert.pem — wss:// не пройдёт проверку TLS"
cp "$REPO_ROOT/packaging/$APP_ID.desktop" "$APPDIR/$APP_ID.desktop"
cp "$REPO_ROOT/packaging/icons/hicolor/256x256/apps/$APP_ID.png" "$APPDIR/$APP_ID.png"
ln -s "$APP_ID.png" "$APPDIR/.DirIcon"

# --- упаковка: runtime + squashfs --------------------------------------------
c_info "Упаковываю ($(du -sh "$APPDIR" | cut -f1))…"
curl -fsSL -o "$WORK/runtime" "$RUNTIME_URL"
mksquashfs "$APPDIR" "$WORK/app.sqfs" -root-owned -noappend -comp zstd -quiet >/dev/null
cat "$WORK/runtime" "$WORK/app.sqfs" > "$OUT"
chmod +x "$OUT"
echo
c_ok "Готово: $OUT ($(du -h "$OUT" | cut -f1))"
echo "  Запуск:  \"$OUT\"   (без FUSE:  \"$OUT\" --appimage-extract-and-run)"

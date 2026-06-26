#! /bin/bash
# Точка входа AppImage. AppRun экспортирует $APPDIR; здесь добавляем bundled
# libsodium в путь поиска (крипто-ядро грузит его через ctypes) и запускаем GUI.
export LD_LIBRARY_PATH="${APPDIR}/libs:${LD_LIBRARY_PATH}"
{{ python-executable }} -m mys_ui "$@"

# Установка МЫС Desktop (Linux)

Нативная установка: приложение появляется в меню (раздел «Интернет/Сеть») с
иконкой и запускается как обычная программа — по образцу VLC и подобных.

## Быстрый старт

```bash
# для текущего пользователя (root не нужен) — рекомендуется
./packaging/install.sh

# если не хватает системных зависимостей (libsodium, python3-venv) — доустановить:
./packaging/install.sh --deps

# для всех пользователей системы:
sudo ./packaging/install.sh --system
```

После установки: ищи «МЫС Desktop» в меню приложений, либо запускай командой
`mys-desktop` из терминала.

## Что делает установщик

1. Проверяет системные зависимости: **libsodium ≥ 1.0.18** (нужен крипто-ядру
   для CPace через `ctypes`) и **Python ≥ 3.13**.
2. Создаёт изолированное окружение (venv) и ставит туда приложение со всеми
   pip-зависимостями (PySide6, cryptography, sqlcipher3 и т.д.) — системный
   Python не засоряется.
3. Ставит лаунчер, `.desktop`-ярлык и иконки (hicolor 16–256px), обновляет
   кэши рабочего стола.

| | Для пользователя (по умолчанию) | Системно (`--system`) |
|---|---|---|
| Окружение | `~/.local/share/mys-desktop/venv` | `/opt/mys-desktop/venv` |
| Лаунчер | `~/.local/bin/mys-desktop` | `/usr/local/bin/mys-desktop` |
| Ярлык | `~/.local/share/applications/` | `/usr/share/applications/` |
| Иконки | `~/.local/share/icons/hicolor/` | `/usr/share/icons/hicolor/` |

Данные пользователя (зашифрованный vault) живут отдельно — в
`~/.local/share/mys/` — и установщик/деинсталлятор их не трогают.

## Удаление

```bash
./packaging/uninstall.sh            # удалить приложение, данные оставить
./packaging/uninstall.sh --purge    # удалить ВМЕСТЕ с vault и историей
sudo ./packaging/uninstall.sh --system
```

## Зависимости по дистрибутивам

Установщик подскажет точную команду, но для справки:

| Дистрибутив | Команда |
|---|---|
| Arch | `sudo pacman -S --needed libsodium python` |
| Debian/Ubuntu | `sudo apt-get install -y libsodium23 python3-venv python3-dev` |
| Fedora | `sudo dnf install -y libsodium python3` |
| openSUSE | `sudo zypper install -y libsodium23 python3` |

---

# Дистрибутивы под несколько ОС

Помимо установки из исходников (выше), проект собирает **готовые нативные
артефакты** под три ОС. Сборка под Windows и macOS возможна только на самих
Windows/macOS (PyInstaller не кросс-компилирует) — поэтому всё автоматизировано
в CI: `.github/workflows/release.yml` собирает все три на «родных» раннерах.

| ОС | Формат | Чем собирается |
|---|---|---|
| Linux | `*.AppImage` (один файл) | `packaging/appimage/build-appimage.sh` |
| Windows | установщик `*-setup.exe` | PyInstaller + Inno Setup |
| macOS | `*.dmg` (внутри `.app`) | PyInstaller |

## Автоматическая сборка (рекомендуется)

```bash
# поставить тег версии — CI соберёт три артефакта и приложит к GitHub Release
git tag v0.1.0
git push origin v0.1.0
```

Либо вручную: вкладка **Actions → build-release → Run workflow** (артефакты
появятся в результатах прогона).

## Linux — AppImage (можно собрать локально)

```bash
./packaging/appimage/build-appimage.sh          # → dist/MYS_Desktop-x86_64.AppImage
```

Самодостаточный файл: внутри изолированный Python, все зависимости и **bundled
libsodium**. Пользователю: `chmod +x MYS_Desktop-x86_64.AppImage && ./MYS_Desktop-x86_64.AppImage`.

## Windows — установщик .exe

Собирается на Windows (или в CI). Локально:

```powershell
pip install . pyinstaller
# нужен libsodium.dll: задать путь к нему
$env:MYS_LIBSODIUM = "C:\path\to\libsodium.dll"
pyinstaller packaging\pyinstaller\mys-desktop.spec    # → dist\mys-desktop\
iscc packaging\windows\installer.iss                  # → dist\mys-desktop-setup-0.1.0.exe
```

Установщик ставит приложение для пользователя (без админа), создаёт ярлыки в меню
«Пуск» и на рабочем столе, регистрирует деинсталлятор.

## macOS — .app / .dmg

Собирается на macOS (или в CI). Локально:

```bash
brew install libsodium
pip install . pyinstaller
bash packaging/macos/make-icns.sh                      # иконка .icns
export MYS_LIBSODIUM="$(brew --prefix libsodium)/lib/libsodium.dylib"
pyinstaller packaging/pyinstaller/mys-desktop.spec     # → dist/МЫС Desktop.app
```

> Сборки не подписаны Apple-сертификатом, поэтому при первом запуске сработает
> Gatekeeper: открыть через **ПКМ → Открыть** (или «Системные настройки →
> Конфиденциальность» → «Всё равно открыть»). Полноценная подпись/нотаризация —
> отдельный шаг, требует платного Apple Developer ID.

## libsodium во всех сборках

Крипто-ядро (CPace для P2P) грузит libsodium через `ctypes`. Загрузчик
(`mys_crypto/_ristretto.py`) ищет библиотеку в порядке: переменная
`MYS_LIBSODIUM` → рядом с приложением (bundled в AppImage/.exe/.app) →
системная. Поэтому P2P-режим работает и в самодостаточных сборках.

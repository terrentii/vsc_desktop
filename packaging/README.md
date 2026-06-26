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

## Дальше (другие ОС / форматы)

Текущий метод — нативная установка через venv + XDG-интеграцию, работает на всех
основных дистрибутивах. Следующие шаги для распространения (по желанию):

- **AppImage** — один скачиваемый файл «запустил и работает», без установки;
- **Flatpak** — песочница + установка через магазины (GNOME Software и пр.);
- **Windows/macOS** — сборка через PyInstaller (`.exe` / `.app`).

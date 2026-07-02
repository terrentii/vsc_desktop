"""Открытые (несекретные) UI-предпочтения: тема и последний режим.

Хранятся через QSettings, а не в vault: тема нужна ДО разблокировки хранилища
(окно входа тоже тематическое), секретов эти значения не содержат.
"""

from PySide6.QtCore import QSettings

_THEMES = ("dark", "light")
_MODES = ("decentralized", "centralized")


def _settings() -> QSettings:
    # Явный IniFormat + UserScope: одинаково на всех ОС и уважает
    # QSettings.setPath (изоляция в тестах).
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "MYS", "MYS Desktop")


def load_theme(default: str = "dark") -> str:
    value = _settings().value("ui/theme")
    return value if value in _THEMES else default


def save_theme(mode: str) -> None:
    if mode in _THEMES:
        _settings().setValue("ui/theme", mode)


def load_mode(default: str = "decentralized") -> str:
    value = _settings().value("ui/mode")
    return value if value in _MODES else default


def save_mode(mode: str) -> None:
    if mode in _MODES:
        _settings().setValue("ui/mode", mode)

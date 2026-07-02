import os

# Headless Qt для тестов — должно быть выставлено до импорта PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture
def fast_kdf():
    """Быстрые KDF-параметры Argon2id для тестов (не для продакшна)."""
    return {"time_cost": 1, "memory_cost": 8, "parallelism": 1}


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path):
    """QSettings (mys_ui.prefs) — во временный ini, не в реальный конфиг юзера."""
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(
        QSettings.IniFormat, QSettings.UserScope, str(tmp_path / "qsettings")
    )

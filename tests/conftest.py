import os

# Headless Qt для тестов — должно быть выставлено до импорта PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture
def fast_kdf():
    """Быстрые KDF-параметры Argon2id для тестов (не для продакшна)."""
    return {"time_cost": 1, "memory_cost": 8, "parallelism": 1}

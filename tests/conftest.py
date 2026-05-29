import os

# Headless Qt для тестов — должно быть выставлено до импорта PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

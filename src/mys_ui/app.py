"""Точка входа: QApplication и маршрутизация окон вход ↔ главное."""

import sys

from PySide6.QtWidgets import QApplication, QStackedWidget

from mys_centralized import CentralizedService

from .controller import AppController
from .theme import apply_theme
from .windows.main_window import MainWindow
from .windows.unlock import UnlockWindow


def _central_factory(vault, *, on_message, on_state_change, on_error):
    """Боевая фабрика: ws_url выводится из server_url входа (см. service)."""
    return CentralizedService(
        vault,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )


class AppShell(QStackedWidget):
    def __init__(self, controller):
        super().__init__()
        self._c = controller
        self.setWindowTitle("МЫС Desktop")
        self._show_unlock()

    def _show_unlock(self) -> None:
        win = UnlockWindow(self._c)
        win.unlocked.connect(self._show_main)
        self._swap(win)

    def _show_main(self) -> None:
        win = MainWindow(self._c)
        win.locked.connect(self._on_lock)
        self._swap(win)

    def _on_lock(self) -> None:
        self._c.lock()
        self._show_unlock()

    def _swap(self, widget) -> None:
        while self.count():
            old = self.widget(0)
            self.removeWidget(old)
            old.deleteLater()
        self.addWidget(widget)
        self.setCurrentWidget(widget)


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, "dark")
    shell = AppShell(AppController(central_factory=_central_factory))
    shell.resize(1180, 760)
    shell.show()
    sys.exit(app.exec())

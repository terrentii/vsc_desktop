"""Точка входа: QApplication и маршрутизация окон вход ↔ главное."""

import sys

from PySide6.QtWidgets import QApplication

from mys_centralized import CentralizedService
from mys_decentralized import P2PService

from . import prefs
from .controller import AppController
from .theme import app_icon, apply_theme
from .windows.frameless import FramelessWindow
from .windows.main_window import MainWindow
from .windows.unlock import UnlockWindow

# Rendezvous-эндпоинт P2P: один порт с веб-сервером, wss:// (см. CLAUDE.md).
_RENDEZVOUS_URL = "wss://soufos.ru/p2p"


def _central_factory(vault, *, on_message, on_state_change, on_error):
    """Боевая фабрика: ws_url выводится из server_url входа (см. service)."""
    return CentralizedService(
        vault,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )


def _p2p_factory(vault, *, on_message, on_state_change, on_error):
    return P2PService(
        vault,
        _RENDEZVOUS_URL,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
    )


class AppShell(FramelessWindow):
    """Безрамочное окно приложения: общий хром + переключение вход ↔ главное."""

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
        while self.content.count():
            old = self.content.widget(0)
            self.content.removeWidget(old)
            old.deleteLater()
        self.content.addWidget(widget)
        self.content.setCurrentWidget(widget)


def main() -> None:
    app = QApplication(sys.argv)
    apply_theme(app, prefs.load_theme())  # тема сохраняется между запусками
    app.setWindowIcon(app_icon())
    shell = AppShell(
        AppController(central_factory=_central_factory, p2p_factory=_p2p_factory)
    )
    shell.resize(1180, 760)
    shell.show()
    sys.exit(app.exec())

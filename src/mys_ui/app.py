"""Точка входа: QApplication и маршрутизация окон вход ↔ главное."""

import os
import sys
from urllib.parse import urlparse

from PySide6.QtWidgets import QApplication

from mys_centralized import CentralizedService
from mys_decentralized import P2PService

from . import motion, prefs
from .controller import AppController
from .theme import app_icon, apply_theme
from .windows.frameless import FramelessWindow
from .windows.main_window import MainWindow
from .windows.unlock import UnlockWindow

# Rendezvous-эндпоинт P2P: один порт с веб-сервером, wss:// (см. CLAUDE.md).
# MYS_RENDEZVOUS_URL — переопределение для LAN-проверки (scripts/run_rendezvous.py).
_RENDEZVOUS_URL = os.environ.get("MYS_RENDEZVOUS_URL", "wss://soufos.ru/p2p")


def _central_factory(vault, *, on_message, on_state_change, on_error, on_room_event=None):
    """Боевая фабрика: ws_url выводится из server_url входа (см. service)."""
    return CentralizedService(
        vault,
        on_message=on_message,
        on_state_change=on_state_change,
        on_error=on_error,
        on_room_event=on_room_event,
    )


def _direct_factory():
    """Фабрика прямого канала WebRTC; None — aiortc не установлен (только relay)."""
    try:
        from mys_decentralized.webrtc import WebRtcLink
    except ImportError:
        return None
    host = urlparse(_RENDEZVOUS_URL).hostname or ""
    # STUN — на хосте сервера (coturn, 3478/udp); в локалке хватает host-кандидатов.
    ice = [] if host in ("127.0.0.1", "localhost") else [f"stun:{host}:3478"]
    return lambda: WebRtcLink(ice)


def _p2p_factory(vault, *, on_message, on_state_change, on_error):
    return P2PService(
        vault,
        _RENDEZVOUS_URL,
        direct_factory=_direct_factory(),
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
        motion.fade_in(widget, 260)  # вход ↔ главное окно — мягкое проявление


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

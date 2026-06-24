"""Панель инструментов: переключатель режима, чипы статуса, вход/настройки/блок."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from mys_ui.controller import CENTRALIZED, DECENTRALIZED


class TopBar(QWidget):
    mode_changed = Signal(str)
    settings_requested = Signal()
    lock_requested = Signal()
    login_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Toolbar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(8)

        self.btn_central = QPushButton("Центр")
        self.btn_p2p = QPushButton("P2P")
        for b in (self.btn_central, self.btn_p2p):
            b.setObjectName("ModeTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_p2p.setChecked(True)
        self.btn_central.clicked.connect(lambda: self._select(CENTRALIZED))
        self.btn_p2p.clicked.connect(lambda: self._select(DECENTRALIZED))

        # чипы статуса
        self.chip = QLabel("")
        self.chip.setObjectName("Chip")
        self.chip.hide()
        self.btn_login = QPushButton("Войти в Центр")
        self.btn_login.setObjectName("PrimaryBtn")
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.clicked.connect(self.login_requested)
        self.btn_login.hide()

        self.btn_settings = QPushButton("Настройки")
        self.btn_settings.setObjectName("BarBtn")
        self.btn_lock = QPushButton("Блокировка")
        self.btn_lock.setObjectName("WarnBtn")
        for b in (self.btn_settings, self.btn_lock):
            b.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.settings_requested)
        self.btn_lock.clicked.connect(self.lock_requested)

        layout.addWidget(self.btn_central)
        layout.addWidget(self.btn_p2p)
        layout.addStretch()
        layout.addWidget(self.chip)
        layout.addWidget(self.btn_login)
        layout.addWidget(self.btn_settings)
        layout.addWidget(self.btn_lock)

    def _select(self, mode: str) -> None:
        self.btn_p2p.setChecked(mode == DECENTRALIZED)
        self.btn_central.setChecked(mode == CENTRALIZED)
        self.mode_changed.emit(mode)

    def update_status(self, mode: str, *, account: str | None) -> None:
        """Отразить режим/сессию: P2P-чип «анонимно», аккаунт-чип или «Войти»."""
        if mode == DECENTRALIZED:
            self.chip.setText("● АНОНИМНО")
            self.chip.show()
            self.btn_login.hide()
        elif account:
            self.chip.setText(f"{account} · soufos.ru")
            self.chip.show()
            self.btn_login.hide()
        else:
            self.chip.hide()
            self.btn_login.show()

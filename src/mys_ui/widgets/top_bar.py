"""Верхняя панель: переключатель режима, настройки, блокировка."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from mys_ui.controller import CENTRALIZED, DECENTRALIZED


class TopBar(QWidget):
    mode_changed = Signal(str)
    settings_requested = Signal()
    lock_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.btn_central = QPushButton("Центр")
        self.btn_p2p = QPushButton("P2P")
        for b in (self.btn_central, self.btn_p2p):
            b.setCheckable(True)
        self.btn_p2p.setChecked(True)
        self.btn_central.clicked.connect(lambda: self._select(CENTRALIZED))
        self.btn_p2p.clicked.connect(lambda: self._select(DECENTRALIZED))

        self.btn_settings = QPushButton("Настройки")
        self.btn_lock = QPushButton("Блокировка")
        self.btn_settings.clicked.connect(self.settings_requested)
        self.btn_lock.clicked.connect(self.lock_requested)

        layout.addWidget(self.btn_central)
        layout.addWidget(self.btn_p2p)
        layout.addStretch()
        layout.addWidget(self.btn_settings)
        layout.addWidget(self.btn_lock)

    def _select(self, mode: str) -> None:
        self.btn_p2p.setChecked(mode == DECENTRALIZED)
        self.btn_central.setChecked(mode == CENTRALIZED)
        self.mode_changed.emit(mode)

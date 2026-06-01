"""Ввод общей секретной фразы и адреса rendezvous для P2P-режима."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

DEFAULT_RENDEZVOUS = "wss://soufos.ru/p2p"


class PhraseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Секретная фраза")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Общая секретная фраза (P2P):"))
        self.field = QLineEdit()
        layout.addWidget(self.field)
        layout.addWidget(QLabel("Rendezvous:"))
        self.rendezvous = QLineEdit(DEFAULT_RENDEZVOUS)
        layout.addWidget(self.rendezvous)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def phrase(self) -> str:
        return self.field.text().strip()

    def rendezvous_url(self) -> str:
        return self.rendezvous.text().strip()

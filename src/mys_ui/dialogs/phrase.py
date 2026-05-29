"""Ввод общей секретной фразы для P2P (стаб — PAKE в под-проекте №4)."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class PhraseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Секретная фраза")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Общая секретная фраза (P2P):"))
        self.field = QLineEdit()
        layout.addWidget(self.field)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def phrase(self) -> str:
        return self.field.text().strip()

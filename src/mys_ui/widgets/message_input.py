"""Поле ввода сообщения."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class MessageInput(QWidget):
    message_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        self.field = QLineEdit()
        self.field.setPlaceholderText("Сообщение…")
        self.btn_send = QPushButton("Отправить")
        layout.addWidget(self.field)
        layout.addWidget(self.btn_send)
        self.btn_send.clicked.connect(self._submit)
        self.field.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        self.field.clear()
        self.message_submitted.emit(text)

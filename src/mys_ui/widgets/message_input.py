"""Строка ввода сообщения: вложение (декоративно) + поле + «Отправить»."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class MessageInput(QWidget):
    message_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InputBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        self.btn_attach = QPushButton("📎")
        self.btn_attach.setObjectName("AttachBtn")
        self.btn_attach.setFixedSize(40, 40)
        self.btn_attach.setCursor(Qt.PointingHandCursor)
        self.btn_attach.setToolTip("Вложения недоступны в P2P v1")

        self.field = QLineEdit()
        self.field.setObjectName("MsgField")
        self.field.setPlaceholderText("Сообщение…")

        self.btn_send = QPushButton("ОТПРАВИТЬ")
        self.btn_send.setObjectName("PrimaryBtn")
        self.btn_send.setCursor(Qt.PointingHandCursor)

        layout.addWidget(self.btn_attach)
        layout.addWidget(self.field, 1)
        layout.addWidget(self.btn_send)

        self.btn_send.clicked.connect(self._submit)
        self.field.returnPressed.connect(self._submit)

    def _submit(self) -> None:
        text = self.field.text().strip()
        if not text:
            return
        self.field.clear()
        self.message_submitted.emit(text)
